"""结构等价校验器：证明「重构前后，一条龙流程做的事一模一样」。

**为什么需要它**

这几条流程都是浏览器自动化：本地跑不了真实流程（要登录 + 真实站点），
单测只能覆盖到"函数被调用了"这一层。要放心地整理它们，就得有别的证据 ——
这个脚本给的就是：把流程函数里有意义的调用按**源码顺序**取出来，
遇到调用项目内自定义函数时**递归展开**（所以"把一段代码抽成 helper"这种
重构在校验器眼里是透明的），再逐项比对。

能抓到的：少了/多了某一步、顺序变了、常量参数（超时、字数、重试次数）被改。
忽略的：纯日志与界面刷新调用（print / log / after / set_status / set_text）。

**用法**

    python tools/dev/flow_equiv.py list                 # 看比对哪些函数
    python tools/dev/flow_equiv.py diff                 # 与 git HEAD 版本比对
    python tools/dev/flow_equiv.py diff ai_auto_chapter # 只比一个

改完流程跑一次 `diff`，看到"全部一致"再提交。历史上的两次拆分/整理都用它兜底。
"""
import ast
import difflib
import subprocess
import sys
from pathlib import Path

# tools/dev/flow_equiv.py → 退两层是仓库根
ROOT = Path(__file__).resolve().parents[2]

TARGETS = {
    "xyxbot/ai/flows.py": ["ai_continue", "ai_review", "ai_auto_chapter", "ai_batch_chapters"],
    "xyxbot/ai/shortcuts.py": ["pick_shortcut", "wait_shortcut_loaded",
                               "open_shortcut_panel"],
    "xyxbot/ai/model.py": ["select_model", "set_associate_level"],
    # ★ 审稿原语已拆成包：目标写成 run 包里的通配（旧版会自动回退到 HEAD 的 review.py）
    "xyxbot/ai/review/*.py": [
        "open_review_pane", "close_review_pane", "review_pane_open",
        "read_review_box", "read_body_settled", "fill_review_text",
        "pick_review_requirement", "start_review", "wait_review_done",
        "replace_review_result",
    ],
    # ★ books 也拆成包了（旧版自动回退到 HEAD 的单文件 books.py）
    "xyxbot/books/*.py": ["open_book", "create_book", "close_activity_modal",
                          "list_books", "goto_books", "is_in_editor"],
    # ★ login 同样拆成包（阶段零的准备入口）
    "xyxbot/login/*.py": ["prepare_session", "ensure_login", "is_ready",
                          "verify_session", "manual_login", "save_session"],
    "xyxbot/ui/pages/ai_flow.py": ["_ai_go", "_ai_review_go", "_ai_both_go", "_ai_batch_go"],
    # ★ 跑章页已拆成包（run/*.py），其中"表单区"又拆成 run/form/*.py：
    #   这些方法名现在分布在不同子模块里，所以分成两个目标。
    "xyxbot/ui/pages/run/*.py": [
        "_page_run", "_run_build_status", "_refresh_run_status", "_run_missing",
        "_refresh_run_todo", "_run_continue_last",
        "_run_local_checks", "_run_show_checks", "_run_precheck",
        "_run_precheck_deep_async", "_run_precheck_deep_done",
        "_run_start", "_run_stop", "_run_clear_results",
        "_run_draw_progress", "_run_render_progress", "_run_progress_sink",
        "_run_apply_progress", "_run_add_result_row",
        "_run_range_to_latest", "_run_export_results", "_run_copy_failed",
        "_run_retry_failed",
    ],
    "xyxbot/ui/pages/run/form/*.py": [
        "_run_build_target", "_run_build_range", "_run_build_template",
        "_run_build_notes", "_run_build_params", "_run_build_progress",
        "_run_params_shortcut", "_run_params_words", "_run_params_review_model",
        "_run_params_review_instruction", "_run_params_review_switches",
        "_run_params_solo_chapter", "_run_params_wrapper",
        "_run_params_solo_tools",
    ],
}

# 纯日志 / 纯界面刷新：与流程语义无关，比对时忽略
IGNORE = {
    "print", "log", "after", "set_status", "set_text", "flush", "format",
    "set_preview", "_set_preview", "update_idletasks", "_refresh_run_status",
    "configure", "config",
}

# 「只看操作」模式（--ops）再排除这些：纯读取 / 纯解析 / 纯字符串处理 ——
# 没有副作用。抽取共用 helper 时"多读一个输入框""多做一次解析"是无害的，
# 但会让完整比对满是噪音。这一模式的真正门槛是：
#   **对站点的操作序列必须一模一样**（点了什么、传了什么超时、调了哪个流程）。
PURE = {
    "get", "strip", "isdigit", "int", "float", "bool", "len", "str", "join",
    "search", "match", "count", "split", "set", "copy", "lower", "upper",
}


def _own_calls(node) -> list:
    """只取这个函数**自己语句**里的调用，顺序 = **实际求值顺序**（后序）。

    · 不深入嵌套函数体：嵌套函数由它自己的条目负责并在调用点展开，
      否则"把内层函数抽成模块级函数"这种重构会误报差异。
    · 后序遍历（先参数、后调用本身）：`f(g())` 的真实顺序是 g → f。
      曾经按源码 (行,列) 排序，结果"把 render_template 的参数提成一行变量"
      这种等价改写被误判成顺序变了 —— 求值顺序才是对的判据。
    """
    found = []

    def rec(n, root):
        for ch in ast.iter_child_nodes(n):
            if isinstance(ch, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)) and ch is not root:
                continue
            if isinstance(ch, ast.Call):
                rec(ch, root)            # 先子后父 = 先求值参数
                f = ch.func
                if isinstance(f, ast.Name):
                    callee = f.id
                elif isinstance(f, ast.Attribute):
                    callee = f.attr
                else:
                    callee = None
                if callee:
                    consts = []
                    for a in ch.args:
                        if isinstance(a, ast.Constant):
                            consts.append(repr(a.value))
                    for kw in ch.keywords:
                        if isinstance(kw.value, ast.Constant):
                            consts.append(f"{kw.arg}={kw.value.value!r}")
                    found.append((callee, tuple(consts)))
            else:
                rec(ch, root)

    rec(node, node)
    return found


def calls_of(src: str) -> dict:
    """{函数名: [(被调用名, 常量参数...), ...]}（顺序 = 求值顺序）。"""
    tree = ast.parse(src)
    out: dict[str, list] = {}

    def visit_func(node):
        out[node.name] = _own_calls(node)
        for ch in node.body:
            if isinstance(ch, (ast.FunctionDef, ast.AsyncFunctionDef)):
                visit_func(ch)

    for n in tree.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            visit_func(n)
        elif isinstance(n, ast.ClassDef):
            for ch in n.body:
                if isinstance(ch, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    visit_func(ch)
    return out


def flatten(name: str, table: dict, seen=None, depth=0, extra_ignore=()) -> list:
    """展开成"做完所有事"的线性序列（本地 helper 递归展开）。"""
    seen = seen or set()
    if name in seen or depth > 12:
        return []
    seen = seen | {name}
    out = []
    for callee, consts in table.get(name, []):
        if callee in IGNORE or callee in extra_ignore:
            continue
        if callee in table:
            # 本地函数：只展开、不记名 —— 提取重构因此变成透明的
            out.extend(flatten(callee, table, seen, depth + 1, extra_ignore))
            continue
        out.append(f"{callee}{consts if consts else ''}")
    return out


def old_src(rel: str) -> str:
    """HEAD 版本的源码。目标带 `*` 时：先试"拆包之前那个单文件"，再回退到通配。

    （例：`pages/run/*.py` 在 HEAD 上其实是单个 `pages/run.py`。）
    """
    if "*" in rel:
        single = rel.split("/*")[0] + ".py"
        blob = subprocess.run(["git", "-C", str(ROOT), "show", f"HEAD:{single}"],
                              capture_output=True, text=True, encoding="utf-8")
        if blob.returncode == 0 and blob.stdout.strip():
            return blob.stdout
        return "\n".join(
            subprocess.run(["git", "-C", str(ROOT), "show",
                            f"HEAD:{p.relative_to(ROOT).as_posix()}"],
                           capture_output=True, text=True,
                           encoding="utf-8").stdout
            for p in sorted(ROOT.glob(rel)))
    return subprocess.run(["git", "-C", str(ROOT), "show", f"HEAD:{rel}"],
                          capture_output=True, text=True, encoding="utf-8").stdout


def new_src(rel: str) -> str:
    if "*" in rel:
        return "\n".join(p.read_text(encoding="utf-8")
                         for p in sorted(ROOT.glob(rel)))
    return (ROOT / rel).read_text(encoding="utf-8")


def main() -> int:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "list"
    ops_only = "--ops" in sys.argv or cmd == "ops"
    only = [a for a in sys.argv[2:] if not a.startswith("-")]

    if cmd == "list":
        for rel, names in TARGETS.items():
            print(f"{rel}: {', '.join(names)}")
        print("\n模式：diff（完整比对） / diff --ops（只看对站点的操作，作为门槛）")
        return 0

    extra = PURE if ops_only else ()
    if ops_only:
        print("模式：只看操作类调用（排除了纯读取/解析/日志）")
    bad = 0
    for rel, names in TARGETS.items():
        old_t, new_t = calls_of(old_src(rel)), calls_of(new_src(rel))
        for name in names:
            if only and name not in only:
                continue
            a = flatten(name, old_t, extra_ignore=extra)
            b = flatten(name, new_t, extra_ignore=extra)
            if a == b:
                print(f"  ✓ {name:<20} 调用序列一致（{len(a)} 步）")
                continue
            bad += 1
            print(f"  ✗ {name:<20} 序列不同：旧 {len(a)} 步 / 新 {len(b)} 步")
            for line in difflib.unified_diff(a, b, "旧", "新", lineterm="", n=2):
                print("      " + line)
    verdict = "有差异：需逐条确认是有意调整还是改坏了" if bad else "全部一致"
    print("\n结论：" + verdict)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())

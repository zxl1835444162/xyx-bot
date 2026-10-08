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
    "xyxbot/ui/pages/ai_flow.py": ["_ai_go", "_ai_review_go", "_ai_both_go", "_ai_batch_go"],
}

# 纯日志 / 纯界面刷新：与流程语义无关，比对时忽略
IGNORE = {
    "print", "log", "after", "set_status", "set_text", "flush", "format",
    "set_preview", "_set_preview", "update_idletasks", "_refresh_run_status",
    "configure", "config",
}


def calls_of(src: str) -> dict:
    """{函数名: [(被调用名, 常量参数...), ...]}，按源码位置排序。"""
    tree = ast.parse(src)
    out: dict[str, list] = {}

    def visit_func(node):
        found = []
        for n in ast.walk(node):
            if isinstance(n, ast.Call):
                f = n.func
                if isinstance(f, ast.Name):
                    callee = f.id
                elif isinstance(f, ast.Attribute):
                    callee = f.attr
                else:
                    continue
                consts = []
                for a in n.args:
                    if isinstance(a, ast.Constant):
                        consts.append(repr(a.value))
                for kw in n.keywords:
                    if isinstance(kw.value, ast.Constant):
                        consts.append(f"{kw.arg}={kw.value.value!r}")
                found.append((n.lineno, n.col_offset, callee, tuple(consts)))
        # ★ 必须按**源码位置**排序：ast.walk 是广度优先，嵌套深度一变顺序就乱，
        #   用它比对会把"提取重构"误判成"顺序改了"（踩过一次）
        found.sort(key=lambda x: (x[0], x[1]))
        out[node.name] = [(callee, consts) for _l, _c, callee, consts in found]
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


def flatten(name: str, table: dict, seen=None, depth=0) -> list:
    """展开成"做完所有事"的线性序列（本地 helper 递归展开）。"""
    seen = seen or set()
    if name in seen or depth > 12:
        return []
    seen = seen | {name}
    out = []
    for callee, consts in table.get(name, []):
        if callee in IGNORE:
            continue
        if callee in table:
            # 本地函数：只展开、不记名 —— 提取重构因此变成透明的
            out.extend(flatten(callee, table, seen, depth + 1))
            continue
        out.append(f"{callee}{consts if consts else ''}")
    return out


def old_src(rel: str) -> str:
    return subprocess.run(["git", "-C", str(ROOT), "show", f"HEAD:{rel}"],
                          capture_output=True, text=True, encoding="utf-8").stdout


def new_src(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def main() -> int:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "list"
    only = [a for a in sys.argv[2:] if not a.startswith("-")]

    if cmd == "list":
        for rel, names in TARGETS.items():
            print(f"{rel}: {', '.join(names)}")
        return 0

    bad = 0
    for rel, names in TARGETS.items():
        old_t, new_t = calls_of(old_src(rel)), calls_of(new_src(rel))
        for name in names:
            if only and name not in only:
                continue
            a = flatten(name, old_t)
            b = flatten(name, new_t)
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

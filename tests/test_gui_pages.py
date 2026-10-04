# -*- coding: utf-8 -*-
"""GUI 页面回归测试（无需 pytest，直接 python 运行）。

★ 2026-10-04 界面重设计后重写。这一版断言的是**新架构**：

  1. 主导航只有 3 项（跑章 / 准备 / 更多），默认落在「跑章」
  2. `show_page` 改成「构建一次、之后只显示/隐藏」
     —— 切页**不再丢编辑**、也**不再销毁**后台任务持有的控件
  3. 「跑章」页一屏装下整条流水线（作品 / 范围 / 指令 / 参数 / 开始 / 停止 / 进度 / 结果）
  4. 「准备」页组合了登录态 + 运行配置
  5. 旧页面（概览/作品/任务/关于…）仍可通过「更多」进入，功能没丢
  6. 页面代码确实按 mixin 拆开（归属检查）
  7. 内容页核心逻辑（#@ 渲染、细纲回写、第几本解析）仍然正确
  8. 原来的死代码（chapters.py 里那份不可达的 AI 流程副本）确实没了

用法：
    .venv312\\Scripts\\python.exe tests\\test_gui_pages.py
"""
from __future__ import annotations

import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# ★ 输出被重定向到文件/管道时，Windows 会用 GBK，日志里的 ⚠ 会让
#   print 直接抛 UnicodeEncodeError（实测退出码 1）。先加固编码。
try:
    from src.console import enable_utf8

    enable_utf8()
except Exception:
    pass

PASS: list[str] = []
FAIL: list[str] = []


def check(name: str, got, want):
    if got == want:
        PASS.append(name)
        print(f"  [PASS] {name}")
    else:
        FAIL.append(name)
        print(f"  [FAIL] {name}: got={got!r} want={want!r}")


def check_true(name: str, cond, detail: str = ""):
    check(name, bool(cond), True)
    if not cond and detail:
        print(f"         {detail}")


def _label_texts(widget) -> list:
    """递归收集某个容器里所有 Label 的文字（用于断言"画出来了什么"）。"""
    out = []
    try:
        kids = widget.winfo_children()
    except Exception:
        return out
    for c in kids:
        try:
            if c.winfo_class() == "Label":
                out.append(str(c.cget("text")))
        except Exception:
            pass
        out += _label_texts(c)
    return out


def _require_display() -> None:
    """没有可用的窗口服务器就**优雅跳过**（而不是报一堆 TclError）。

    ★ 为什么需要（2026-10-04 上 CI）：
      GitHub Actions 的 runner 是没有图形会话的。macOS runner 有时候能建
      Tk 窗口、有时候不能（取决于镜像），Linux runner 基本一定不能。
      与其让 CI 红一片，不如明确地打印 SKIP 并以 0 退出 —— 这样
      "在 macOS 上把 GUI 真的跑起来"这件事变成**尽力而为**，
      而真正的跨平台逻辑由 test_portability.py 保证。
    """
    try:
        import tkinter as tk

        r = tk.Tk()
        r.withdraw()
        r.destroy()
    except Exception as e:
        print("\n" + "=" * 60)
        print(f"  SKIP：本环境没有可用的窗口服务器，跳过 GUI 测试")
        print(f"        原因：{type(e).__name__}: {str(e)[:120]}")
        print("        （跨平台逻辑由 tests/test_portability.py 覆盖）")
        print("=" * 60)
        sys.stdout.flush()
        os._exit(0)


_require_display()


# ==================================================== 1. 窗口与页面构建
print("=== 1. 窗口与页面构建 ===")
# ★★ 先把工作区配置文件指向临时路径，再建窗口 ——
#   `artifacts/storage/workspace.json` 里是**用户真实的跑章配置**
#   （小说路径 / 作品名 / 那段 250 字的指令模板），测试绝不能覆盖它。
import pathlib as _pl
import tempfile

from src import workspace as _WS

_WS.WS_FILE = _pl.Path(tempfile.mkdtemp(prefix="xyx-gui-test-")) / "ws.json"
#   同理，小说「轻量记忆」也不能指到用户真实文件
from src import config as _C

_C.LAST_PROJECT = _WS.WS_FILE.parent / "last_project.json"

from ui.defaults import DEFAULT_PAGE, EXTRA_PAGES, NAV_ITEMS, PAGE_ALIASES
from ui.main_window import MainWindow

win = MainWindow(username="tester")
win.withdraw()

# --- 导航：3 项，默认跑章
check("主导航正好 3 项", len(NAV_ITEMS), 3)
check("导航项 = 跑章/准备/更多", [k for k, _i, _l in NAV_ITEMS],
      ["run", "setup", "more"])
check("默认页是跑章", DEFAULT_PAGE, "run")
check("初始落在跑章", win._current, "run")
check_true("跑章页已构建", "run" in win._pages)

# --- 所有页面都能切换（3 个新的 + 6 个旧的）
PAGES = [k for k, _i, _l in NAV_ITEMS] + list(EXTRA_PAGES.keys())
built = []
for p in PAGES:
    win.show_page(p)
    built.append(p)
check("10 个页面都能切换且不报错", built, PAGES)

# --- ★ 兼容映射：旧 key "content" 落到 run
win.show_page("content")
check("旧 key 'content' 落到跑章页", win._current, "run")
check_true("PAGE_ALIASES 里有 content", "content" in PAGE_ALIASES)

# --- ★★ 构建一次、显示/隐藏（这是本轮修掉"切页丢编辑"的关键）
check("页面被缓存（不是每次重建）", len(win._pages), len(PAGES))
_run_frame = win._pages["run"]
win.show_page("setup")
win.show_page("run")
check_true("切走再回来还是同一个 Frame（没被销毁重建）",
           win._pages["run"] is _run_frame)

# 直接验证"切页不丢编辑"
win.show_page("run")
win._tpl_text.delete("1.0", "end")
win._tpl_text.insert("1.0", "未保存的编辑内容ABC")
win.show_page("more")
win.show_page("run")
check_true("切页后指令模板里的未保存编辑还在",
           "未保存的编辑内容ABC" in win._tpl_text.get("1.0", "end"),
           repr(win._tpl_text.get("1.0", "end"))[:80])

# 只有当前页是 pack 的
try:
    packed = [k for k, f in win._pages.items() if f.winfo_manager()]
    check("同时只显示一个页面", packed, ["run"])
except Exception as e:
    check_true("同时只显示一个页面", False, str(e))

# ==================================================== 2. 跑章页控件
print("\n=== 2. 「跑章」页：整条流水线都在这一页 ===")
win.show_page("run")
RUN_WIDGETS = [
    # 状态条
    "_run_status_lbl", "_run_status_dot",
    # ① 目标作品
    "_ai_book_entry", "_ai_idx_entry",
    # ② 跑章范围
    "_batch_start_entry", "_batch_end_entry", "_batch_autonew_var",
    "_batch_stop_on_fail_var", "_run_range_hint",
    # ③ 每章指令
    "_tpl_text", "_tpl_preview", "_tpl_state", "_code_hint",
    # ④ 细纲来源（折叠）
    "_novel_entry", "_split_hint", "_hist_box", "_ch_list", "_ch_canvas",
    # ⑤ 高级参数（折叠）
    "_ai_shortcut_entry", "_ai_min_entry", "_ai_max_entry",
    "_ai_retry_entry", "_ai_auto_var",
    "_rv_model_entry", "_rv_card_entry", "_rv_assoc_entry", "_rv_req_entry",
    "_rv_instr_text", "_rv_timeout_entry", "_rv_select_all_var",
    "_rv_replace_var", "_rv_chapter_entry",
    # 单章工具（备用）
    "_btn_ai_go", "_btn_ai_review", "_btn_ai_both", "_auto_both_close_var",
    "_ai_ch_var", "_ai_ch_menu",
    # ⑥ 操作
    "_btn_run_start", "_btn_run_stop", "_btn_ai_batch",
    # ⑦ 进度 + 结果
    "_run_progress_canvas", "_run_progress_lbl", "_run_timing_lbl",
    "_run_res_canvas", "_run_res_list", "_run_checks_box",
]
_missing = [c for c in RUN_WIDGETS if not hasattr(win, c)]
check_true(f"跑章页 {len(RUN_WIDGETS)} 个控件齐全", not _missing,
           f"missing={_missing}")

check_true("「停止」按钮初始为禁用（没跑时不误导）",
           getattr(win, "_btn_run_stop")._enabled is False
           if hasattr(win._btn_run_stop, "_enabled") else True)

# 指令模板编辑框要够大（用户那段模板约 250 字，旧版只有 3 行）
check_true("指令模板编辑框 ≥8 行",
           int(win._tpl_text.cget("height")) >= 8,
           f"height={win._tpl_text.cget('height')}")

# 预检能用，且没填东西时能报错（不是静默通过）
win._ai_book_entry.set("")
win._batch_start_entry.set("0")
win._batch_end_entry.set("0")
_checks = win._run_local_checks()
check_true("预检能跑出结果", len(_checks) >= 4, str(len(_checks)))
from src.runplan import has_blocking_error
check_true("没填作品/范围时预检报阻塞", has_blocking_error(_checks))

# 填好关键项后不该再阻塞
win._ai_book_entry.set("新建作品12")
win._batch_start_entry.set("3")
win._batch_end_entry.set("10")
win._run_site_chapters = [1, 2, 3, 4, 5, 6, 7]
win._refresh_run_range_hint()
_checks = win._run_local_checks()
_errs = [c.title for c in _checks if c.is_error]
check_true("填好作品/范围后不再有范围类阻塞",
           not any("范围" in t or "作品名" in t for t in _errs), str(_errs))
check_true("范围提示写清了要新建几章",
           "需要新建" in win._run_range_hint.cget("text"),
           win._run_range_hint.cget("text"))

# 结果表的增删
win._run_clear_results()
check("清空后没有结果行", len(win._run_res_list.winfo_children()), 0)
# ★ 走真实入口 `_run_apply_progress`（它先更新 Progress，再画结果行）
win._run_apply_progress({"no": 3, "ok": True, "words": 2210,
                         "elapsed": 130.0, "reason": "", "phase": "done",
                         "total": 3, "done_count": 1, "ok_count": 1,
                         "total_elapsed": 130.0})
win._run_apply_progress({"no": 4, "ok": False, "words": 0, "elapsed": 60.0,
                         "reason": "生成超时", "phase": "done",
                         "total": 3, "done_count": 2, "ok_count": 1,
                         "total_elapsed": 190.0})
win._run_apply_progress({"no": 5, "aborted": True, "ok": False,
                         "elapsed": 5.0, "phase": "done", "total": 3,
                         "done_count": 3, "ok_count": 1,
                         "total_elapsed": 195.0})
check("结果表 3 行", len(win._run_res_list.winfo_children()), 3)
check("进度里记下了失败章", win._run_progress.failed, [4])
check("进度里记下了中止章", win._run_progress.aborted, [5])
check_true("进度条画出了 100%",
           win._run_progress.percent == 100.0, str(win._run_progress.percent))
check_true("进度行可读（含 3/3）", "3/3" in win._run_progress.line(),
           win._run_progress.line())
check_true("进度行标出了失败与中止",
           "失败 4" in win._run_progress.line()
           and "已中止" in win._run_progress.line(),
           win._run_progress.line())

# 「从失败章重跑」把范围设好
win._batch_end_entry.set("10")
win._run_retry_failed()
check("重跑把起始章设成最小失败章", win._batch_start_entry.get(), "4")
check("重跑保留原结束章", win._batch_end_entry.get(), "10")

# ★★ 停止按钮真的接到了后端中止开关（不只是画了个按钮）
from src import ai as _AI

_AI.clear_cancel()
check_true("起始时没有中止请求", not _AI.cancel_requested())
win._run_set_stop_enabled(True)
win._run_stop()
check_true("点「停止」→ 后端收到中止请求", _AI.cancel_requested())
win._run_set_stop_enabled(False)
_AI.clear_cancel()
check_true("收尾后中止标记被清掉（不会让下次开局就被中止）",
           not _AI.cancel_requested())

# ==================================================== 3. 新增的可用性功能
print("\n=== 3. 本轮新增：待办引导 / 接着上次继续 / 结果导出 / 日志过滤 ===")

# ---- 3.1 「还差什么」待办列表 ----
win.show_page("run")
win._ai_book_entry.set("")
win._batch_start_entry.set("0")
win._batch_end_entry.set("0")
win._project = None
from src.novel import NovelProject as _NP, split_novel as _split

_missing = win._run_missing()
check_true("缺作品名/范围/细纲时列出待办", len(_missing) >= 3,
           str(_missing))
check_true("待办每项都是 (说明, 按钮文字, 回调)",
           all(len(t) == 3 for t in _missing))
win._refresh_run_todo()
check_true("待办区被画出来了",
           len(win._run_todo_box.winfo_children()) >= 1)

# 补齐之后待办应该清空
win._ai_book_entry.set("新建作品12")
win._batch_start_entry.set("3")
win._batch_end_entry.set("10")
win._project = _NP(name="t", chapters=_split("第1章 a\n正文。\n"))
_missing = win._run_missing()
check_true("补齐作品名/范围后不再报这两项",
           not any("作品" in t[0] or "范围" in t[0] for t in _missing),
           str(_missing))

win._refresh_run_todo()
_todo_text = " ".join(_label_texts(win._run_todo_box))
check_true("补齐后待办区能渲染出文字", bool(_todo_text),
           repr(_todo_text)[:80])

# 故意留一项缺失，确认提示里点名了它
win._ai_book_entry.set("")
win._refresh_run_todo()
_todo_text = " ".join(_label_texts(win._run_todo_box))
check_true("缺作品名时待办区点名「目标作品」",
           "目标作品" in _todo_text, repr(_todo_text)[:120])
check_true("待办区给出了「还差」的标题",
           "还差" in _todo_text, repr(_todo_text)[:120])
win._ai_book_entry.set("新建作品12")

# ---- 3.2 「接着上次继续」----
from src.workspace import note_batch_run as _note

_note(10, 8)                       # 假装上次跑完到第 10 章、共 8 章
win._refresh_run_last()
check_true("刷新后能指出上次跑到第 10 章",
           "10" in win._run_last_lbl.cget("text"),
           win._run_last_lbl.cget("text"))
win._batch_start_entry.set("1")
win._batch_end_entry.set("1")
win._run_continue_last()
check("接着上次继续 → 起始章 = 11", win._batch_start_entry.get(), "11")
check("接着上次继续 → 结束章 = 18（沿用段长 8）",
      win._batch_end_entry.get(), "18")

# ---- 3.3 「拉结束章到最新」----
win._run_site_chapters = [1, 2, 3, 4, 5, 6, 7]
win._batch_start_entry.set("3")
win._batch_end_entry.set("3")
win._run_range_to_latest()
check("拉到最新 → 起始章不变", win._batch_start_entry.get(), "3")
check("拉到最新 → 结束章 = 站点最大章", win._batch_end_entry.get(), "7")

# 站点章节未知时不能瞎改，只提示
win._run_site_chapters = None
win._batch_end_entry.set("5")
win._run_range_to_latest()
check("站点章节未知时不改范围", win._batch_end_entry.get(), "5")

# ---- 3.4 结果导出 / 复制失败章号 ----
win._run_clear_results()
check("清空后原始结果数据也清空", win._run_results_data, [])
win._run_apply_progress({"no": 3, "ok": True, "words": 2210,
                         "elapsed": 130.0, "phase": "done", "total": 3,
                         "done_count": 1, "ok_count": 1})
win._run_apply_progress({"no": 4, "ok": False, "words": 0, "elapsed": 61.5,
                         "reason": "生成超时", "phase": "done", "total": 3,
                         "done_count": 2, "ok_count": 1})
check("原始结果数据记了 2 条", len(win._run_results_data), 2)

import csv as _csv
from src import config as _C

_ex_dir = _C.ARTIFACTS / "exports"
_before = set(_ex_dir.glob("跑章结果-*.csv")) if _ex_dir.exists() else set()
win._run_export_results()
_after = set(_ex_dir.glob("跑章结果-*.csv"))
_new = _after - _before
check_true("导出后多了一个 CSV 文件", len(_new) == 1, str(_new))
if _new:
    _p = _new.pop()
    _txt = _p.read_text(encoding="utf-8-sig")
    _rows = list(_csv.reader(_txt.splitlines()))
    check("CSV 有表头 + 2 行数据", len(_rows), 3)
    check("CSV 表头正确", _rows[0][0], "章号")
    check_true("CSV 记下了失败原因",
               any("生成超时" in r[4] for r in _rows[1:]), _txt[:120])
    check_true("CSV 里成功章标为「成功」",
               any(r[1] == "成功" for r in _rows[1:]))
    _p.unlink()      # 清掉测试产物

win._run_copy_failed()
try:
    _clip = win.clipboard_get()
except Exception:
    _clip = ""
check_true("复制失败章号到剪贴板（4）", _clip.strip() == "4", repr(_clip))

# ---- 3.5 日志「只看关键节点」过滤 ----
from ui.theme import LogView as _LV

_lv = _LV(win, height=3)
_lv.log("切换页面：跑章", "info")          # 噪音
_lv.log("✓ 第3章完成", "ok")               # 关键
_lv.log("提示：某某某", "dim")             # 噪音
_lv.log("✗ 第4章失败", "err")              # 关键
_content_before = _lv.text.get("1.0", "end")
check_true("默认不过滤（noise 不 elide）",
           str(_lv.text.tag_cget("noise", "elide")) in ("0", "false", "False"),
           str(_lv.text.tag_cget("noise", "elide")))
check_true("默认 key_only=False", _lv.key_only() is False)
_lv.set_key_only(True)
check_true("开启后 key_only=True", _lv.key_only() is True)
check_true("开启后 noise 标签被设为 elide=True",
           str(_lv.text.tag_cget("noise", "elide")) in ("1", "true", "True"),
           str(_lv.text.tag_cget("noise", "elide")))
check_true("★ 过滤是无损的：Text 内容一字没少",
           _lv.text.get("1.0", "end") == _content_before)
_lv.set_key_only(False)
check_true("关掉过滤恢复显示",
           str(_lv.text.tag_cget("noise", "elide")) in ("0", "false", "False"))
check_true("toggle 能来回切", _lv.toggle_key_only() is True)
_lv.destroy()

# 主界面上的开关也在
check_true("日志面板上有「只看关键节点」勾选框",
           hasattr(win, "_log_keyonly"))
win._set_log_keyonly(True)
check_true("主界面开关生效", win.log_view.key_only() is True)
win._set_log_keyonly(False)
check_true("主界面开关能关掉", win.log_view.key_only() is False)

# ==================================================== 4. 准备 / 更多
print("\n=== 4. 「准备」与「更多」页 ===")
win.show_page("setup")
check_true("准备页：组合了登录态卡", hasattr(win, "_acc_badge"))
check_true("准备页：组合了运行配置", hasattr(win, "_browser_entry"))
check_true("准备页：有自己的状态显示", hasattr(win, "_setup_lbl"))
check_true("准备页：能刷新状态",
           callable(getattr(win, "_refresh_setup", None)))

win.show_page("more")
check_true("更多页：列出旧页面入口", hasattr(win, "_page_more"))
from ui.pages.more import MORE_ITEMS
check_true("更多页至少 6 个入口", len(MORE_ITEMS) >= 6, str(len(MORE_ITEMS)))
_names = {k for k, _t, _d in MORE_ITEMS}
check_true("更多页能进概览", "overview" in _names)
check_true("更多页能进关于", "about" in _names)

# ==================================================== 4. 旧页面仍然可用
print("\n=== 5. 旧页面（从导航撤下但没删）===")
win.show_page("overview")
check_true("overview: 指标卡 + 平台能力卡",
           len(win._pages["overview"].winfo_children()) >= 2)
win.show_page("account")
check_true("account: 状态徽标", hasattr(win, "_acc_badge"))
check_true("account: 立即保存按钮", hasattr(win, "_btn_save_session"))
win.show_page("books")
check_true("books: 名称输入框", hasattr(win, "_book_entry"))
check_true("books: 打开按钮", hasattr(win, "_btn_open_book"))
win.show_page("tasks")
check_true("tasks: 任务名列表可读", isinstance(win._task_names(), list))
win.show_page("settings")
check_true("settings: 浏览器路径输入框", hasattr(win, "_browser_entry"))

# ==================================================== 6. mixin 归属
print("\n=== 5. 页面代码确实已拆出（mixin 归属） ===")
from ui.pages import (AboutPage, AccountPage, AiFlowMixin, BooksPage,
                      ChaptersMixin, ConfigIOMixin, MorePage, OverviewPage,
                      RunMixin, SettingsPage, SetupMixin, TasksPage)

OWNERSHIP = [
    (RunMixin, ["_page_run", "_run_local_checks", "_run_show_checks",
                "_run_start", "_run_stop", "_run_retry_failed",
                "_run_progress_sink", "_run_apply_progress",
                "_run_add_result_row", "_run_draw_progress",
                "_refresh_run_status", "_run_set_stop_enabled"]),
    (SetupMixin, ["_page_setup", "_refresh_setup"]),
    (MorePage, ["_page_more"]),
    (AboutPage, ["_page_about"]),
    (OverviewPage, ["_page_overview"]),
    (AccountPage, ["_page_account", "_start_login", "_verify_session",
                   "_prepare_go", "_prepare_refresh"]),
    (BooksPage, ["_page_books", "_open_book", "_show_alts", "_list_all_books"]),
    (TasksPage, ["_page_tasks"]),
    (SettingsPage, ["_page_settings", "_detect_browser"]),
    (ConfigIOMixin, ["_restore_ws", "_collect_ws", "_save_ws",
                     "_render_history"]),
    (ChaptersMixin, ["_do_split", "_render_chapters", "_set_tpl",
                     "_get_instruction", "_update_tpl_preview",
                     "_collect_notes", "_save_project", "_open_project",
                     "_refresh_ai_chapter_menu", "_current_ai_chapter",
                     "_resolve_current_chapter_no", "_parse_book_index"]),
    (AiFlowMixin, ["_ai_go", "_ai_review_go", "_ai_both_go", "_ai_batch_go",
                   "_on_ai_done", "_on_review_done", "_on_both_done",
                   "_on_batch_done"]),
]
for cls, names in OWNERSHIP:
    for n in names:
        check_true(f"{n} 在 {cls.__name__}", n in cls.__dict__,
                   f"仍在 MainWindow.__dict__: {n in MainWindow.__dict__}")

# ★ 死代码必须真的没了：AI 流程只能有 ai_flow.py 一份实现
check_true("ChaptersMixin 不再重复实现 _ai_batch_go",
           "_ai_batch_go" not in ChaptersMixin.__dict__)
check_true("ChaptersMixin 不再重复实现 _ai_go",
           "_ai_go" not in ChaptersMixin.__dict__)
_chap_src = (ROOT / "ui" / "pages" / "chapters.py").read_text(encoding="utf-8")
_chap_lines = len(_chap_src.splitlines())
# 这条是"别再胖回去"的粗粒度护栏：删掉 606 行重复代码后是 ~400 行，
# 2026-10-04 又加了「轻量记忆」约 100 行 → 508。真正的不变量是上面那两条
# `not in ChaptersMixin.__dict__`，行数只是防止再堆成上帝模块。
check_true(f"chapters.py 没有重新膨胀（{_chap_lines} 行 < 700）",
           _chap_lines < 700, f"{_chap_lines} 行（删重复代码前是 1034 行）")
check_true("确实生效的是 AiFlowMixin 的实现",
           MainWindow._ai_batch_go.__qualname__.startswith("AiFlowMixin"),
           MainWindow._ai_batch_go.__qualname__)

# 窗口类只该留骨架
KEPT = ["__init__", "_build", "show_page", "_page_header", "_ensure_app",
        "_stop_app", "_browser_path_override", "_ensure_page", "_make_app",
        "_session_log", "_run_guarded", "_run_task", "_keep_on_top",
        "log", "_on_window_close", "_logout", "_task_names",
        "_page_builders", "_page_labels"]
for n in KEPT:
    check_true(f"MainWindow 保留骨架 {n}", n in MainWindow.__dict__)

# ==================================================== 6. 核心逻辑
print("\n=== 7. 分章 / 指令模板 / 细纲 核心逻辑 ===")
from src.novel import NovelProject, split_novel

win.show_page("run")
proj = NovelProject(name="t", chapters=split_novel(
    "第1章 a\n正文一。\n第2章 b\n正文二。\n第3章 c\n正文三。\n"))
proj.set_note(1, "细纲一")
proj.set_note(2, "细纲二")
proj.set_note(3, "细纲三")
win._project = proj
win._refresh_ai_chapter_menu()

check("默认当前章 = 1", win._resolve_current_chapter_no(), 1)
win._ai_ch_var.set("#3 第3章 c")
check("选中第3章 → 3", win._resolve_current_chapter_no(), 3)

# #@ 渲染（G4 修复的回归）
proj.instruction = "根据 #@ 续写，参考 #1。"
plot = proj.render_template(proj.instruction,
                            current=win._resolve_current_chapter_no())
check_true("#@ 被替换为第3章细纲", "细纲三" in plot, plot)
check_true("#1 保持绝对引用", "细纲一" in plot, plot)
check_true("无残留 #@", "#@" not in plot, plot)
check_true("预览无残留 #@",
           "#@" not in win._tpl_preview.get("1.0", "end"), "")

# 第几本解析（G3 修复的回归）
win._ai_idx_entry.set("")
check("留空 → (None, True)", win._parse_book_index(), (None, True))
win._ai_idx_entry.set("2")
check("'2' → (2, True)", win._parse_book_index(), (2, True))
win._ai_idx_entry.set("abc")
check("非法 → (None, False)", win._parse_book_index(), (None, False))
check("非法输入清空状态", win._ai_book_index, None)
win._ai_idx_entry.set("0")

# 配置编解码（含本轮新增的跑章范围持久化）
fields = win._collect_ws()
check_true("_collect_ws 返回 24+ 字段", len(fields) >= 24, f"got {len(fields)}")
check_true("含 book_name", "book_name" in fields)
check_true("含 review_card", "review_card" in fields)
check_true("★ 含 batch_start（本轮新增持久化）", "batch_start" in fields)
check_true("★ 含 batch_end", "batch_end" in fields)
check_true("★ 含 batch_auto_new", "batch_auto_new" in fields)
check_true("★ 含 batch_stop_on_fail", "batch_stop_on_fail" in fields)

# 章节列表渲染与回读
win._render_chapters()
check("章节输入框数量 = 3", len(win._ch_entries), 3)
win._ch_entries[1].set("改过的细纲")
win._collect_notes()
check("细纲回写到工程", win._project.find(1).note, "改过的细纲")

# ==================================================== 7. 浏览器路径持久化
print("\n=== 8. 浏览器路径持久化（G8 修复的回归）===")
win.show_page("settings")
win._browser_entry.set(r"C:\fake\msedge.exe")
check("browser path 读取", win._browser_path_override(), r"C:\fake\msedge.exe")
win._browser_entry.destroy()
check("控件销毁后仍可读（持久字段）",
      win._browser_path_override(), r"C:\fake\msedge.exe")

# ==================================================== 9. 记忆功能
print("\n=== 9. 记忆功能：存了之后能恢复回来 ===")

# ---- 9.1 界面/环境类字段：写进 workspace → _restore_ws 应用 ----
from src.workspace import save_ws as _save_ws_raw

_save_ws_raw(book_name="记忆测试作品", book_index="1",
             browser_path=r"C:\x\msedge.exe",
             log_key_only=True, auto_both_close=False,
             batch_start="8", batch_end="15")
win.show_page("run")
win._restore_ws()          # ← 模拟"重新打开程序"时的恢复动作
check("作品名被恢复", win._ai_book_entry.get(), "记忆测试作品")
check("同名第几本被恢复", win._ai_idx_entry.get(), "1")
check("跑章起始章被恢复", win._batch_start_entry.get(), "8")
check("跑章结束章被恢复", win._batch_end_entry.get(), "15")
check("★ 浏览器内核路径被恢复",
      win._browser_path_override(), r"C:\x\msedge.exe")
check("★ 日志「只看关键节点」被恢复", win.log_view.key_only(), True)
check("★ 单章「自动关弹窗」被恢复", win._auto_both_close_var.get(), False)
_save_ws_raw(log_key_only=False, auto_both_close=True)   # 还原，免得影响后文

# ---- 9.2 小说「轻量记忆」：存 → 清空 → 恢复（含界面控件）----
_M_TXT = _WS.WS_FILE.parent / "记忆小说.txt"
_M_TXT.write_text("第1章 a\n正文甲。\n第2章 b\n正文乙。\n", encoding="utf-8")
_mproj = _NP.load(_M_TXT)
win._project = _mproj
win._render_chapters()
win._ch_entries[2].set("第二章细纲XYZ")      # 用户在界面上手填细纲
check_true("保存轻量记忆成功", win._save_last_project() is True)
check_true("轻量记忆文件已生成", _C.LAST_PROJECT.exists())

# 模拟重启：内存里的工程丢掉
win._project = None
win._ch_entries = {}
check_true("恢复轻量记忆成功", win._restore_last_project() is True)
check_true("工程回来了", win._project is not None)
if win._project is not None:
    check("章数恢复", len(win._project.chapters), 2)
    check("★ 手填的细纲从磁盘恢复", win._project.find(2).note,
          "第二章细纲XYZ")
    check("★ 章节列表控件也按恢复结果重建", len(win._ch_entries), 2)
    check("★ 输入框里显示的就是恢复的细纲",
          win._ch_entries[2].get(), "第二章细纲XYZ")
    check("source 指向原 txt", str(win._project.source), str(_M_TXT))

# 再恢复一次不该把已有的覆盖掉（幂等保护）
_before_proj = win._project
win._restore_last_project()
check_true("已有工程时 _restore_last_project 不覆盖",
           win._project is _before_proj)

# ==================================================== 10. 关窗清理
print("\n=== 10. 关窗清理（必须放在最后：它会 destroy 整个窗口）===")
win._on_window_close()
check("关窗清理不抛异常", True, True)

# ---------------------------------------------------------------- 汇总
print("\n" + "=" * 60)
print(f"  通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
if FAIL:
    print("  失败列表：")
    for f in FAIL:
        print(f"    - {f}")
print("=" * 60)

# ★ 硬退出：GUI 里有常驻 pw 线程与 after 回调，正常退出可能被拖住
# ★ flush 必须加：os._exit 不会刷缓冲区，
#   一旦把输出重定向到文件/管道，测试结果就整个丢了（实测踩过）。
sys.stdout.flush()
sys.stderr.flush()
os._exit(1 if FAIL else 0)

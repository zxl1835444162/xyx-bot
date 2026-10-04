# -*- coding: utf-8 -*-
"""回归测试：「登录窗 → 主界面」这条路径必须通。

无需 pytest，直接 `python tests/test_login_flow.py`。

★★ 为什么单独测这条路径（2026-10-04 用户在 macOS 上实测报的问题）
================================================================

用户的现象：**能进登录界面、输完授权码之后，第二个页面（主界面）出不来。**

真实代码路径是这样的（`ui/login_window.py`）：

    self.after(420, lambda: self._enter(user))     # ← 在 Tk 回调里
    def _enter(self, user):
        self.destroy()                             # 登录窗先销毁了
        self._on_success(user)                     # → launch_main → MainWindow(...)

也就是说：

  * 如果 `MainWindow(...)` 抛异常，**登录窗已经没了**，用户什么都看不到；
  * 回调里的异常会交给 `report_callback_exception`，而它默认只把堆栈
    `print` 到 **stderr** —— 打包成 .app 后 `console=False`，stderr 没有去处。

结果就是：**点了没反应、没有任何报错**。这正是用户看到的样子。

所以本文件覆盖三件事：

  A. 真实顺序能不能走通：先建登录窗 → 销毁 → 再建主窗
     （同一个进程里前后建两个 Tk root —— macOS 的 Aqua Tk 对这件事
      一向比 Windows/Linux 挑剔，是本次最可疑的点）
  B. 主窗口 + 全部 9 个页面都能构建
  C. 回调异常**不再被静默吞掉**：`report_callback_exception` 必须被
     换成会记日志的实现（打包版才查得到原因）

没有图形会话时整体优雅 SKIP（退出码 0），这样 CI 的 Linux runner 也能跑。
"""
from __future__ import annotations

import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# CI / 自动化：不许弹模态窗（会把 runner 卡死）
os.environ.setdefault("XYX_NO_DIALOG", "1")

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


# ---------------------------------------------------------------- 有没有图形会话
def _require_display() -> None:
    try:
        import tkinter as tk

        r = tk.Tk()
        r.withdraw()
        r.destroy()
    except Exception as e:
        print("\n" + "=" * 60)
        print(f"  SKIP：本环境没有可用的窗口服务器（{type(e).__name__}）")
        print("        （这条路径的验证需要图形会话）")
        print("=" * 60)
        sys.stdout.flush()
        os._exit(0)


_require_display()

# ==================================================== A. 异常处理器
print("=== A. Tk 回调异常必须被记录，不能静默吞掉 ===")
import run_gui  # noqa: E402

check_true("run_gui 提供 _install_error_handler", 
           hasattr(run_gui, "_install_error_handler"))
check_true("run_gui 提供 _log_fatal（写文件，打包版才查得到）",
           hasattr(run_gui, "_log_fatal"))
check_true("run_gui 提供 _dialog_allowed（CI 里要能关掉模态窗）",
           hasattr(run_gui, "_dialog_allowed"))
check_true("XYX_NO_DIALOG=1 时不弹窗", run_gui._dialog_allowed() is False)

import tkinter as tk  # noqa: E402

_orig = tk.Tk.report_callback_exception
try:
    run_gui._install_error_handler()
    check_true("安装后 report_callback_exception 被替换掉了",
               tk.Tk.report_callback_exception is not _orig)

    # 直接调一次处理器：不能抛异常，而且要把堆栈写进日志
    from src import config as C

    log = C.LOGS / "fatal.log"
    before = log.stat().st_size if log.exists() else 0
    root = tk.Tk()
    root.withdraw()
    try:
        try:
            raise ZeroDivisionError("测试用的假异常")
        except ZeroDivisionError:
            # ★ 要显式传 self（root）：直接 `tk.Tk.report_callback_exception(*exc)`
            #   是未绑定调用，Python 不会自动补 self，会报缺参数。
            tk.Tk.report_callback_exception(root, *sys.exc_info())
        check_true("处理器调用不抛异常", True)
        grew = (log.stat().st_size if log.exists() else 0) > before
        check_true(f"堆栈被写进了 {log.name}", grew)
        if log.exists():
            tail = log.read_text(encoding="utf-8", errors="replace")[-400:]
            check_true("日志里含异常类型", "ZeroDivisionError" in tail,
                       tail[-200:])
    finally:
        try:
            root.destroy()
        except Exception:
            pass
finally:
    tk.Tk.report_callback_exception = _orig

# ==================================================== B/C. 真实路径
print("\n=== B. 主窗口 + 9 个页面都能构建 ===")
from src.selftest import smoke_main_window  # noqa: E402

rc = smoke_main_window(verbose=True)
check("smoke_main_window 返回 0（两条路径都通过）", rc, 0)
check_true("（这一步同时覆盖了 B「9 个页面」与 C「登录窗销毁后再建主窗」）",
           True)

# ==================================================== D. 静态检查
print("\n=== D. 静态检查：launch_main 不能再裸奔 ===")
_rg = (ROOT / "run_gui.py").read_text(encoding="utf-8")
check_true("launch_main 里包了 try/except（失败要弹出来）",
           "主界面启动失败" in _rg)
check_true("main() 里先装异常处理器再建窗口",
           _rg.index("_install_error_handler()") < _rg.index("LoginWindow("))
check_true("--selftest 默认连界面一起冒烟",
           'want_ui = "--no-ui" not in sys.argv' in _rg)
_sel = (ROOT / "src" / "selftest.py").read_text(encoding="utf-8")
check_true("冒烟里会真的去建登录窗（复现用户那条路）",
           "LoginWindow(" in _sel)
# ★ 只"构造"窗口是测不出"窗口没显示"的 —— 必须跑真实事件循环
check_true("冒烟里有真实事件循环探测（mainloop + winfo_viewable）",
           "mainloop()" in _sel and "winfo_viewable" in _sel)
check_true("探测有兜底超时（after(ms + 3000, ...)），不会死等",
           "ms + 3000" in _sel)
# ★★ 但事件循环探测在 GitHub 的 macOS runner 上会**永久卡住**（实测踩过：
#    两个 job 卡了 8 分钟以上只能手动取消），所以必须在 CI 里自动关闭。
check_true("窗口探测在 CI 环境自动关闭（检测 CI 环境变量）",
           "os.getenv(\"CI\")" in _sel and "_window_probe_wanted" in _sel)
check_true("可以用 XYX_SELFTEST_WINDOW 显式开关",
           "XYX_SELFTEST_WINDOW" in _sel)
check_true("默认冒烟会 withdraw（不映射窗口，任何环境都安全）",
           "win.withdraw()" in _sel)
_wf = (ROOT / ".github" / "workflows" / "build-macos.yml").read_text(
    encoding="utf-8")
_tw = (ROOT / ".github" / "workflows" / "tests.yml").read_text(encoding="utf-8")
check_true("CI 两个工作流都设了 timeout-minutes（防死等烧额度）",
           "timeout-minutes" in _wf and "timeout-minutes" in _tw)
_mw = (ROOT / "ui" / "main_window.py").read_text(encoding="utf-8")
check_true("主窗口会显式把自己推到前台（_present）",
           "def _present" in _mw and "self.attributes(\"-topmost\", True)" in _mw)
check_true("置顶会在 400ms 后撤掉，不长期霸占",
           "self.after(400, _unpin)" in _mw)
check_true("任务置顶期间不会被 _present 的撤顶误伤",
           "_topmost_on" in _mw and "def _keep_on_top" in _mw)

# ★★ 启动看门狗：卡死必须能自己把现场写下来
#    用户的 mac 版是「主界面永远不出来 + 鼠标转圈」，而且我在别的机器上
#    复现不了。没法复现就必须让**卡死自己报告卡在哪一行**。
print("\n=== E. 启动看门狗（卡死要能自己写出主线程栈） ===")
check_true("run_gui 有启动看门狗", hasattr(run_gui, "_install_startup_watchdog"))
check_true("run_gui 有进度信标", hasattr(run_gui, "_beacon"))
check_true("run_gui 有卡死报告函数", hasattr(run_gui, "_dump_hang"))
check_true("看门狗只武装在启动阶段（起来后可撤）",
           hasattr(run_gui, "_arm_watchdog") and hasattr(run_gui, "_disarm_watchdog"))
check_true("阈值可以用环境变量调整",
           "XYX_HANG_SECONDS" in _rg)
check_true("主界面起来后会撤掉看门狗（否则正常 idle 会误报）",
           "_disarm_watchdog()" in _rg)
check_true("进度信标埋在关键节点上（登录窗/主界面）",
           "_beacon(" in _rg and _rg.count("_beacon(") >= 5)

# 真的调一次 _dump_hang，确认能把主线程栈写进日志
from src import config as C  # noqa: E402

_fatal = C.LOGS / "fatal.log"
# ★ 只看**这次新追加**的那一段：报告里有"所有线程"一长串，
#   用文件尾部 N 个字符去断言会被挤掉（我第一版就是这么错的）
_before = _fatal.read_text(encoding="utf-8", errors="replace") \
    if _fatal.exists() else ""
run_gui._beacon("测试用信标")
run_gui._dump_hang(99.0, "单元自检")
_after = _fatal.read_text(encoding="utf-8", errors="replace") \
    if _fatal.exists() else ""
_added = _after[len(_before):]
check_true("卡死报告写进了 fatal.log", len(_added) > 120,
           f"只多了 {len(_added)} 字")
check_true("报告里含主线程调用栈", "主线程调用栈" in _added)
check_true("报告里含最后一次进展（便于定位阶段）", "测试用信标" in _added)
check_true("报告里标了平台/是否打包（mac vs win 一眼区分）",
           "平台：" in _added and "打包：" in _added)
check_true("报告里给出了主线程的帧（能指到具体行）",
           "run_gui.py" in _added or "test_login_flow.py" in _added)

# ---------------------------------------------------------------- 汇总
print("\n" + "=" * 60)
print(f"  通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
if FAIL:
    print("  失败列表：")
    for f in FAIL:
        print(f"    - {f}")
print("=" * 60)

sys.stdout.flush()
sys.stderr.flush()
os._exit(1 if FAIL else 0)

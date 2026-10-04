# -*- coding: utf-8 -*-
"""★★ 回归测试：「登录 → 主界面」必须能在**真实事件循环**里跑完。

    python tests/repro_login.py

这个文件存在的唯一理由（2026-10-04）
====================================

用户 macOS 上反馈：登录界面正常，点确定之后**登录窗消失、鼠标一直转圈、
主界面永远不出来、没有任何报错**。

根因（在真 macOS runner 上复现出来了）：老代码把 `mainloop()` **嵌套**了 ——

    root1.mainloop()                     ← LoginWindow
      └─ 回调 _enter（点登录）
           ├─ root1.destroy()
           └─ root2.mainloop()           ← MainWindow，嵌在里面且 root1 已销毁

Windows 的 Tk 能扛；macOS 的 Aqua Tk 不行 —— root #2 收不到任何事件：
窗口不绘制、`after` 定时器不触发、鼠标转圈、**还不抛异常**（所以零提示）。

真机实测的卡死现场：
    ★ 卡死了：主线程已 10.4 秒没有任何进展
       最后一次进展：MainWindow.__init__ 结束      ← 窗口建好了
       平台：darwin                                 ← 然后 mainloop 死了

为什么以前所有测试都没抓到
==========================

`test_gui_pages.py` / `smoke_main_window` **只构造窗口、从不跑 mainloop**，
所以"窗口建好了但事件循环死了"这种问题它们天然看不见。
本文件补的就是这一块：**用真实 mainloop 走完整流程**。

同时它还带一个看门狗：万一将来又卡住，会直接把主线程栈打出来
（而不是像以前那样"一片红但不知道卡在哪"）。
"""
from __future__ import annotations

import faulthandler
import os
import pathlib
import sys
import threading
import time
import traceback

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
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
try:
    import tkinter as tk

    _r = tk.Tk()
    _r.withdraw()
    _r.destroy()
except Exception as e:
    print("\n" + "=" * 64)
    print(f"  SKIP：本环境没有可用的窗口服务器（{type(e).__name__}）")
    print("=" * 64)
    sys.stdout.flush()
    os._exit(0)

faulthandler.enable()

STALL_LIMIT = float(os.getenv("XYX_HANG_SECONDS", "15") or 15)
T0 = time.time()
MARKS: list = []
LOCK = threading.Lock()
DONE = threading.Event()
HUNG = {"yes": False}


def mark(label: str) -> None:
    with LOCK:
        MARKS.append((label, time.time() - T0))
    print(f"  [{time.time() - T0:6.2f}s] {label}", flush=True)


def _idle() -> float:
    with LOCK:
        return (time.time() - T0) - (MARKS[-1][1] if MARKS else 0.0)


def watchdog() -> None:
    """主线程停滞超过 STALL_LIMIT 就 dump 它的栈 —— 直接指出卡在哪一行。"""
    while not DONE.is_set():
        time.sleep(0.5)
        if _idle() > STALL_LIMIT:
            HUNG["yes"] = True
            label = MARKS[-1][0] if MARKS else "(无)"
            print("\n" + "!" * 72, flush=True)
            print(f"  ★ 卡死了：主线程已 {_idle():.1f} 秒没有任何进展", flush=True)
            print(f"     最后一次进展：{label}", flush=True)
            print(f"     平台：{sys.platform}", flush=True)
            print("!" * 72, flush=True)
            main_id = threading.main_thread().ident
            fr = sys._current_frames().get(main_id)
            print("\n--- 主线程调用栈（最上面 = 卡住的那一行）---", flush=True)
            if fr is not None:
                for line in traceback.format_stack(fr):
                    print("  " + line.rstrip(), flush=True)
            print("\n--- 所有线程 ---", flush=True)
            faulthandler.dump_traceback()
            DONE.set()
            time.sleep(0.5)
            os._exit(3)
        if time.time() - T0 > STALL_LIMIT + 40:
            DONE.set()
            time.sleep(0.3)
            os._exit(4)


threading.Thread(target=watchdog, name="repro-watchdog", daemon=True).start()

# ================================================================ 准备
print("=" * 72)
print("  回归：登录 → 主界面（真实事件循环）")
print(f"  平台 {sys.platform} | locale LC_ALL={os.getenv('LC_ALL')!r}")
print(f"  停滞阈值 {STALL_LIMIT:.0f}s")
print("=" * 72)

import run_gui  # noqa: E402
from ui import theme  # noqa: E402
import ui.login_window as LW  # noqa: E402
import ui.main_window as MW  # noqa: E402

# 数一下字体解析次数（顺带守住"别反复枚举系统字体"）
_real_resolve = theme._resolve_family
font_calls = {"n": 0}


def _spy(candidates, env_var):
    font_calls["n"] += 1
    return _real_resolve(candidates, env_var)


theme._resolve_family = _spy

INSTANCES: list = []
VISIBLE_CHECKED = {"yes": False}


class SpyMainWindow(MW.MainWindow):
    """记录主窗口实例，并在窗口起来后检查"事件循环到底有没有在跑"。"""

    def __init__(self, *a, **kw):
        mark("MainWindow.__init__ 开始")
        super().__init__(*a, **kw)
        mark("MainWindow.__init__ 结束")
        INSTANCES.append(self)

        def _check():
            # ★ 这个回调能不能被触发，就是"事件循环活没活"的判据。
            #   老代码（嵌套 mainloop）下它**永远不会触发**。
            try:
                v = self.winfo_viewable()
                st = self.state()
                mark(f"主窗口事件循环在跑：viewable={v} state={st} "
                     f"geometry={self.geometry()}")
                VISIBLE_CHECKED["yes"] = True
            except Exception as e:
                mark(f"可见性检查失败 {type(e).__name__}: {e}")
            try:
                self.quit()          # 收工，让 run_app 的 mainloop 返回
            except Exception:
                pass

        self.after(1500, _check)


MW.MainWindow = SpyMainWindow

# 自动登录：900ms 后填表并走真实的 _do_login
_real_login_init = LW.LoginWindow.__init__


def _auto_login_init(self, *a, **kw):
    _real_login_init(self, *a, **kw)
    mark("LoginWindow 已创建，排定自动登录")

    def _drive():
        try:
            self.entry_user.set("tester")
            self.entry_key.set("ZSJT-2026-VIP")
            mark("点击「登 录」（真实 _do_login）")
            self._do_login()
        except Exception:
            mark("_do_login 抛异常")
            traceback.print_exc()

    self.after(900, _drive)


LW.LoginWindow.__init__ = _auto_login_init

# ================================================================ 跑
rc = None
try:
    rc = run_gui.run_app()
except BaseException:
    mark("run_app 抛异常")
    traceback.print_exc()

DONE.set()
mark("run_app 返回")

# ================================================================ 断言
print()
print("=" * 72)
print("  结果")
print("=" * 72)
check("run_app 正常返回（没卡死、没异常）", rc, 0)
check("主窗口被创建了 1 次", len(INSTANCES), 1)
# ★★ 这一条是这次 bug 的核心：窗口建好 ≠ 事件循环活着
check_true("★ 主窗口的事件循环真的在跑（after 回调被触发）",
           VISIBLE_CHECKED["yes"],
           "窗口建好了但事件循环没跑 —— 就是 macOS 上那个卡死")
check_true("看门狗没有报卡死", not HUNG["yes"])

_rg = (ROOT / "run_gui.py").read_text(encoding="utf-8")
print("\n  --- 结构检查（防止有人把嵌套 mainloop 写回来）---")
check_true("run_gui 有顶层循环 run_app", "def run_app(" in _rg)
check_true("登录窗的 mainloop 在顶层调用（_login_once 里）",
           "def _login_once(" in _rg and "lw.mainloop()" in _rg)
check_true("run_app 里平级调用 MainWindow 的 mainloop",
           "win.mainloop()" in _rg)
_lw = (ROOT / "ui" / "login_window.py").read_text(encoding="utf-8")
check_true("LoginWindow._enter 不再自己 destroy 登录窗",
           "self.destroy()\n        self._on_success" not in _lw)
check_true("LoginWindow._enter 用 quit() 让事件循环正常返回",
           "self.quit()" in _lw)
# 全局扫一遍：mainloop 只应该在顶层出现。
# ★ 用 AST 找真正的调用节点 —— 直接扫文本会把 docstring 里的示例代码也算进去，
#   而且 Windows 下路径是反斜杠，startswith("ui/") 会误判（我第一版就这么错的）。
import ast  # noqa: E402

_mainloops: list = []
for p in list((ROOT / "ui").rglob("*.py")) + [ROOT / "run_gui.py",
                                              ROOT / "main.py"]:
    try:
        tree = ast.parse(p.read_text(encoding="utf-8"))
    except SyntaxError:
        continue
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "mainloop"):
            _mainloops.append(
                f"{p.relative_to(ROOT).as_posix()}:{node.lineno}")
check("mainloop() 只在 run_gui.py 顶层出现（ui/ 里不许有）", len(_mainloops), 2)
check_true("两处都在 run_gui.py（_login_once 与 run_app）",
           all(m.startswith("run_gui.py:") for m in _mainloops),
           str(_mainloops))

print(f"\n  字体解析调用 {font_calls['n']} 次，"
      f"枚举 {theme._FONT_DIAG.get('families_ms')} ms / "
      f"{theme._FONT_DIAG.get('families_count')} 个族")

print()
print("  时间线：")
prev = 0.0
for label, t in MARKS:
    print(f"    {t:7.2f}s  (+{t - prev:5.2f}s)  {label}")
    prev = t

print("\n" + "=" * 64)
print(f"  通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
if FAIL:
    print("  失败列表：")
    for f in FAIL:
        print(f"    - {f}")
print("=" * 64)

for w in INSTANCES:
    try:
        w.destroy()
    except Exception:
        pass
sys.stdout.flush()
sys.stderr.flush()
os._exit(1 if FAIL else 0)

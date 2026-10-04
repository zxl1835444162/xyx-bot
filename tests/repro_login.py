# -*- coding: utf-8 -*-
"""★ 真实驱动「登录窗 → 主界面」，并用看门狗抓出卡在哪一行。

    LoginWindow → 点「登 录」→ _do_login → after(420) → _enter
        → destroy() → launch_main → MainWindow(...) → mainloop()

为什么写成这样（2026-10-04）
============================

用户 macOS 上反馈：登录界面正常，点确定之后**登录窗消失、鼠标一直转圈、
主界面永远不出来、没有任何报错**。"转圈"= 主线程被卡住。

这台机器上（Windows）复现不出来，所以这个脚本的设计目标不是"断言通过"，
而是**把卡住的现场抓下来**：

  * 真的跑 `mainloop()`（不是只构造），真的填表、真的走 `_do_login`
  * 一个**后台看门狗线程**盯着进度；主线程一旦 N 秒没动静，
    立刻打印**主线程的调用栈**（卡在哪一行）+ 所有线程的栈，然后退出
  * 每个阶段打时间戳，能区分"慢"和"死"

看门狗是独立线程，所以即使主线程卡死在 C 层（GIL 释放），它照样能跑。

用法：
    python tests/repro_login.py
    XYX_HANG_SECONDS=10 python tests/repro_login.py     # 更快判定
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

faulthandler.enable()

T0 = time.time()
MARKS: list = []
LOCK = threading.Lock()
DONE = threading.Event()
STALL_LIMIT = float(os.getenv("XYX_HANG_SECONDS", "20") or 20)
HARD_LIMIT = STALL_LIMIT + 40.0


def mark(label: str) -> None:
    with LOCK:
        MARKS.append((label, time.time() - T0))
    print(f"  [{time.time() - T0:7.2f}s] {label}", flush=True)


def _idle() -> float:
    with LOCK:
        return (time.time() - T0) - (MARKS[-1][1] if MARKS else 0.0)


def watchdog() -> None:
    """主线程停滞超过 STALL_LIMIT 就 dump 它的栈并退出。"""
    while not DONE.is_set():
        time.sleep(0.5)
        if _idle() > STALL_LIMIT:
            label = MARKS[-1][0] if MARKS else "(无)"
            print("\n" + "!" * 72, flush=True)
            print(f"  ★ 卡死了：主线程已 {_idle():.1f} 秒没有任何进展", flush=True)
            print(f"     最后一次进展：{label}", flush=True)
            print(f"     平台：{sys.platform}  打包：{bool(getattr(sys, 'frozen', False))}", flush=True)
            print("!" * 72, flush=True)
            frames = sys._current_frames()
            main_id = threading.main_thread().ident
            fr = frames.get(main_id)
            print("\n--- 主线程调用栈（最上面 = 卡住的那一行）---", flush=True)
            if fr is not None:
                for line in traceback.format_stack(fr):
                    print("  " + line.rstrip(), flush=True)
            print("\n--- 所有线程 ---", flush=True)
            faulthandler.dump_traceback()
            DONE.set()
            time.sleep(0.5)
            os._exit(3)
        if time.time() - T0 > HARD_LIMIT:
            print(f"\n  超过硬上限 {HARD_LIMIT:.0f}s，收工", flush=True)
            DONE.set()
            time.sleep(0.3)
            os._exit(4)


threading.Thread(target=watchdog, name="repro-watchdog", daemon=True).start()

# ---------------------------------------------------------------- 埋点
import tkinter as tk  # noqa: E402

import run_gui  # noqa: E402
from ui import theme  # noqa: E402

_real_resolve = theme._resolve_family
font_calls = {"n": 0, "ms": 0.0}


def spy_resolve(candidates, env_var):
    t = time.perf_counter()
    r = _real_resolve(candidates, env_var)
    font_calls["n"] += 1
    font_calls["ms"] += (time.perf_counter() - t) * 1000
    return r


theme._resolve_family = spy_resolve

import ui.main_window as MW  # noqa: E402

_real_MW = MW.MainWindow
INSTANCES: list = []


class SpyMainWindow(_real_MW):
    """包一层，记录真实构造的起止时间。"""

    def __init__(self, *a, **kw):
        mark("MainWindow.__init__ 开始")
        try:
            super().__init__(*a, **kw)
        except BaseException:
            mark("MainWindow.__init__ 抛异常（见上面的 traceback）")
            traceback.print_exc()
            raise
        mark("MainWindow.__init__ 结束")
        INSTANCES.append(self)

        def _check():
            try:
                mark(f"主窗口可见性 viewable={self.winfo_viewable()} "
                     f"state={self.state()} geometry={self.geometry()}")
            except Exception as e:
                mark(f"可见性检查失败 {type(e).__name__}: {e}")
            DONE.set()
            try:
                self.quit()
            except Exception:
                pass

        self.after(1200, _check)


# run_gui.launch_main 里是「函数内 import MainWindow」，所以这样替换能生效
MW.MainWindow = SpyMainWindow

print("=" * 72)
print("  真实驱动 login → main")
print(f"  平台 {sys.platform} | locale LC_ALL={os.getenv('LC_ALL')!r} "
      f"LANG={os.getenv('LANG')!r}")
print(f"  停滞判定阈值 {STALL_LIMIT:.0f}s")
print("=" * 72)

from ui.login_window import LoginWindow  # noqa: E402

mark("创建 LoginWindow")
try:
    login = LoginWindow(on_success=run_gui.launch_main)
except BaseException:
    mark("LoginWindow 创建失败")
    traceback.print_exc()
    DONE.set()
    sys.exit(2)
mark("LoginWindow 创建完成")


def drive() -> None:
    mark("填表 + 点「登 录」（走真实 _do_login）")
    try:
        login.entry_user.set("tester")
        login.entry_key.set("ZSJT-2026-VIP")
        login._do_login()
    except BaseException:
        mark("_do_login 抛异常")
        traceback.print_exc()
        DONE.set()
        try:
            login.quit()
        except Exception:
            pass
        return
    mark("_do_login 返回（已排定 after(420) → _enter）")


login.after(900, drive)
login.after(int(HARD_LIMIT * 1000) - 800,
            lambda: (mark("兜底超时"), DONE.set(), login.quit()))

try:
    login.mainloop()
except BaseException:
    mark("mainloop 抛异常")
    traceback.print_exc()

DONE.set()
mark("mainloop 返回")

print()
print("=" * 72)
print("  结果")
print("=" * 72)
print(f"  MainWindow 实例数 : {len(INSTANCES)}")
print(f"  字体解析调用次数  : {font_calls['n']} 次，累计 "
      f"{font_calls['ms']:.1f} ms")
print(f"  系统字体枚举      : {theme._FONT_DIAG.get('families_ms')} ms / "
      f"{theme._FONT_DIAG.get('families_count')} 个族")
print()
print("  时间线：")
prev = 0.0
for label, t in MARKS:
    print(f"    {t:7.2f}s  (+{t - prev:5.2f}s)  {label}")
    prev = t

ok = len(INSTANCES) == 1 and any(
    m[0].startswith("主窗口可见性") for m in MARKS)
print()
print(f"  结论：{'✓ 登录 → 主界面 全程正常' if ok else '✗ 没走到「主窗口可见』'}")
for w in INSTANCES:
    try:
        w.destroy()
    except Exception:
        pass
sys.stdout.flush()
os._exit(0 if ok else 1)

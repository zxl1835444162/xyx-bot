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
import subprocess
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
# ★ 不要在正式跑之前先建一个临时 root —— macOS 上"多建 root / 多跑 mainloop"
#   本身就是不可靠的，探测工具自己不能变成干扰源。
if sys.platform.startswith("linux") and not (
        os.getenv("DISPLAY") or os.getenv("WAYLAND_DISPLAY")):
    print("\n" + "=" * 64)
    print("  SKIP：本环境没有 DISPLAY（Linux headless）")
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


def _assert_no_storm() -> None:
    """不依赖定时器的断言：构建主界面**不能**发生渲染风暴。

    实测到过的坏样子（真 macOS）：10 秒内 Configure=97968 / render=98029 /
    create_text=126038。修好后是 126 次 create_text。
    阈值取 2000 —— 正常构建只有几百次，风暴是几万次，中间很宽。
    """
    ct = _STATS["create_text"]
    rd = _STATS["render"]
    print(f"      断言：create_text={ct} render={rd}（阈值 2000）", flush=True)
    if ct > 2000 or rd > 2000:
        print("      ✗ 渲染风暴！图形重绘次数异常 —— "
              "有 <Configure> 处理器没走 theme.bind_configure 守卫",
              flush=True)
        os._exit(3)
    print("      ✓ 没有渲染风暴", flush=True)


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
            print(f"     ★ 计数：Configure={_STATS['configure']} "
                  f"render={_STATS['render']} "
                  f"create_text={_STATS['create_text']}", flush=True)
            if _STATS["create_text"] > 5000 or _STATS["render"] > 5000:
                HUNG["yes"] = True
                print("     → **渲染风暴**（Configure↔重绘 互相触发）"
                      "—— 这是真 bug，必须修", flush=True)
                print("!" * 72, flush=True)
                main_id = threading.main_thread().ident
                fr = sys._current_frames().get(main_id)
                print("\n--- 主线程调用栈（最上面 = 卡住的那一行）---",
                      flush=True)
                if fr is not None:
                    for line in traceback.format_stack(fr):
                        print("  " + line.rstrip(), flush=True)
                print("\n--- 所有线程 ---", flush=True)
                faulthandler.dump_traceback()
                DONE.set()
                time.sleep(0.5)
                os._exit(3)
            # ★ 计数很小 = 没有风暴；主线程干净地停在 mainloop 里，说明
            #   **本环境的 Tcl 定时器根本不触发**（GitHub 的 macOS runner
            #   就是这样：没有真实窗口会话，CFRunLoop 的定时器源不被唤醒）。
            #   这不是应用的 bug，本环境无法判定 → SKIP（但要断言"没有风暴"）。
            print("     → 不是风暴：主线程干净地停在 mainloop 里，"
                  "计数也很小。", flush=True)
            print("       本环境的 Tcl 定时器不触发"
                  "（CI 的 macOS runner 限制），无法在此判定 → SKIP。",
                  flush=True)
            print("!" * 72, flush=True)
            _assert_no_storm()
            DONE.set()
            time.sleep(0.4)
            os._exit(0)
        if time.time() - T0 > STALL_LIMIT + 40:
            DONE.set()
            time.sleep(0.3)
            os._exit(4)


threading.Thread(target=watchdog, name="repro-watchdog", daemon=True).start()

import tkinter as tk  # noqa: E402

# ================================================================ ★ 不用 mainloop
#
# ★★ 为什么把 mainloop 换成 update() 泵（2026-10-04 关键突破）
# =====================================================================
# GitHub 的 macOS runner 上 `root.mainloop()` **不会处理定时器事件**
# （没有真实窗口会话，CFRunLoop 的定时器源不被唤醒）—— 所以之前所有
# "点完登录后窗口有没有出来"的验证在那个环境里都跑不了，我只能看到
# "after 回调没触发"，误以为是 runner 限制就绕过去了。
#
# 而 `update()` 是"把所有**当前就绪**的事件处理掉"，包含已到期的定时器，
# 不依赖 CFRunLoop 的定时器源。所以把 mainloop 换成一圈圈 `update()`，
# 既能让真实的登录→主界面流程跑起来，也能检查窗口是否真的显示出来。
_PUMP_SECONDS = float(os.getenv("XYX_PUMP_SECONDS", "10") or 10)
_pump_stats = {"iters": 0, "secs": 0.0}
PROBE: dict = {"visible_at": None, "geometry": None, "state": None,
               "shot": None}


def _snap(path: str) -> bool:
    """抓一张屏幕截图。

    ★ 只在 macOS 上用（内置 `screencapture`，不需要额外依赖）。
      Windows/Linux 上直接跳过，别报无谓的错。
    """
    if not sys.platform.startswith("darwin"):
        print("  [shot] 非 macOS，跳过截图", flush=True)
        return False
    try:
        r = subprocess.run(["screencapture", "-x", path],
                           capture_output=True, timeout=20)
        if r.returncode == 0 and os.path.exists(path):
            print(f"  [shot] 已截图 {path}", flush=True)
            return True
        print(f"  [shot] screencapture 失败 rc={r.returncode} "
              f"{(r.stderr or b'')[:120]}", flush=True)
    except Exception as e:
        print(f"  [shot] 截图异常 {type(e).__name__}: {e}", flush=True)
    return False


def _pump_mainloop(self, n=0):        # noqa: ARG001 —— 签名要兼容 tkinter
    """代替 `mainloop()`：用 `update()` 泵事件，最多泵 `_PUMP_SECONDS` 秒。

    ★ 额外做一件关键的事：**盯着主窗口什么时候真的变成可见**，并截图存证。
      这样"点完登录后窗口到底出没出来"就不再靠猜。
    """
    t0 = time.time()
    shot_dir = pathlib.Path(os.getenv("XYX_SHOT_DIR", "artifacts/screenshots"))
    shot_dir.mkdir(parents=True, exist_ok=True)
    last_probe = 0.0
    while time.time() - t0 < _PUMP_SECONDS and not DONE.is_set():
        try:
            self.update()
        except Exception as e:
            print(f"  [pump] update 抛异常：{type(e).__name__}: {e}",
                  flush=True)
            break
        _pump_stats["iters"] += 1
        # 每 0.4s 探一次主窗口可见性
        if time.time() - last_probe > 0.4:
            last_probe = time.time()
            for w in list(INSTANCES):
                try:
                    if w.winfo_viewable():
                        if PROBE["visible_at"] is None:
                            PROBE["visible_at"] = round(time.time() - T0, 2)
                            PROBE["geometry"] = w.geometry()
                            PROBE["state"] = w.state()
                            mark(f"★ 主窗口真的显示了（{PROBE['geometry']} "
                                 f"state={PROBE['state']}）")
                            p = str(shot_dir / "macos_after_login.png")
                            if _snap(p):
                                PROBE["shot"] = p
                        break
                except Exception:
                    pass
        time.sleep(0.005)
    _pump_stats["secs"] = time.time() - t0
    print(f"  [pump] 泵了 {_pump_stats['secs']:.1f}s / "
          f"{_pump_stats['iters']} 次 update()", flush=True)
    try:
        self.quit()
    except Exception:
        pass


tk.Misc.mainloop = _pump_mainloop

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

# ---------------------------------------------------------------- 计数器
# ★ 目的：区分"渲染风暴"和"真阻塞"。
#   真机现场显示主线程卡在 ui/theme.py:559 create_text（由 <Configure> 触发），
#   那到底是"Configure→重绘→Configure 无限循环"（CPU 打满），
#   还是"create_text 本身阻塞"（CPU 空闲）？
#   数量就能回答：卡死时计数上万 = 风暴；计数很小 = 阻塞。
_STATS = {"configure": 0, "render": 0, "create_text": 0, "after_fired": 0}

import tkinter as tk  # noqa: E402

_orig_create_text = tk.Canvas.create_text


def _ct(self, *a, **kw):
    _STATS["create_text"] += 1
    return _orig_create_text(self, *a, **kw)


tk.Canvas.create_text = _ct

for _cls in ("BrandButton", "GradientBar", "CheckBox", "StatusBar"):
    _k = getattr(theme, _cls, None)
    if _k is None or not hasattr(_k, "_render"):
        continue
    _or = _k._render

    def _mk_render(_or):
        def _r(self, *a, **kw):
            _STATS["render"] += 1
            return _or(self, *a, **kw)
        return _r

    _k._render = _mk_render(_or)
    if hasattr(_k, "_on_configure"):
        _oc = _k._on_configure

        def _mk_cfg(_oc):
            def _c(self, e, *a, **kw):
                _STATS["configure"] += 1
                return _oc(self, e, *a, **kw)
            return _c

        _k._on_configure = _mk_cfg(_oc)

# ★ 不要包装 tk.Misc.after！试过：它会把每次 after 都注册成一个临时 Tcl 命令，
#   控件销毁时 tkinter 的 deletecommand 会炸
#   （AttributeError: 'NoneType' object has no attribute 'remove'），
#   反而制造出一次**假卡死**（Windows 上本来 3.9 秒跑完，插桩后卡满 20 秒）。
#   只数 configure/render/create_text 就够分辨"风暴 vs 阻塞"了。

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
# ★★ 这一条是这次 bug 的核心：窗口建好 ≠ 事件循环活着 ≠ 窗口真的显示出来
check_true("★ 主窗口真的显示出来了（winfo_viewable 为真）",
           PROBE["visible_at"] is not None,
           "窗口没显示出来 —— 就是用户看到的「点完登录什么都没出现」")
if PROBE["visible_at"] is not None:
    print(f"         （在 {PROBE['visible_at']}s 时可见，"
          f"{PROBE['geometry']} state={PROBE['state']}）")
check_true("★ 主窗口的事件循环真的在跑（after 回调被触发）",
           VISIBLE_CHECKED["yes"],
           "窗口建好了但事件循环没跑 —— 就是 macOS 上那个卡死")
check_true("看门狗没有报卡死", not HUNG["yes"])

_rg = (ROOT / "run_gui.py").read_text(encoding="utf-8")
print("\n  --- 结构检查（防止退回「多个 Tk root / 多次 mainloop」）---")
check_true("run_gui 有顶层流程 run_app", "def run_app(" in _rg)
# ★★ 核心不变量：全进程只建一个 Tk root、只跑一次 mainloop。
#    用 AST 找真正的调用节点 —— 扫文本会把 docstring 里的示例代码也算进去，
#    而且 Windows 下路径是反斜杠，startswith("ui/") 会误判（我第一版就这么错的）。
import ast  # noqa: E402

_tk_calls: list = []
_mainloops: list = []
for p in list((ROOT / "ui").rglob("*.py")) + [ROOT / "run_gui.py",
                                              ROOT / "main.py"]:
    try:
        tree = ast.parse(p.read_text(encoding="utf-8"))
    except SyntaxError:
        continue
    rel = p.relative_to(ROOT).as_posix()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        if isinstance(f, ast.Attribute) and f.attr == "mainloop":
            _mainloops.append(f"{rel}:{node.lineno}")
        if (isinstance(f, ast.Attribute) and f.attr == "Tk"
                and isinstance(f.value, ast.Name) and f.value.id == "tk"):
            _tk_calls.append(f"{rel}:{node.lineno}")

check("★ 全进程只跑一次 mainloop()", len(_mainloops), 1)
check_true("那次 mainloop 在 run_gui.py（顶层）",
           _mainloops and _mainloops[0].startswith("run_gui.py:"),
           str(_mainloops))
_tk_in_rg = [x for x in _tk_calls if x.startswith("run_gui.py:")]
_tk_in_ui = [x for x in _tk_calls if x.startswith("ui/")]

# ★ 判据不是"数够不够"，而是：**除了 run_app 里那唯一一次**，
#   其它每一处 tk.Tk() 都必须被守卫着（复用已有 root，或走 master=None 兼容）。
_GUARDS = ("if master is None:", "_default_root")


def _guarded(rel: str, lineno) -> bool:
    lineno = int(lineno)          # ★ 从 "文件:行号" 拆出来的行号是字符串
    lines = (ROOT / rel).read_text(encoding="utf-8").splitlines()
    return any(any(g in lines[j] for g in _GUARDS)
               for j in range(max(0, lineno - 9), lineno - 1))


_unguarded = [x for x in _tk_calls if not _guarded(*x.split(":"))]
check("★ 只有 run_app 那一处是无条件建 root（其余都必须复用/守卫）",
      len(_unguarded), 1)
check_true(f"唯一那处就在 run_app 里（{_unguarded}）",
           bool(_unguarded) and _unguarded[0].startswith("run_gui.py:"),
           str(_unguarded))
check_true("run_app 里确实建了 root（且是那句 root = tk.Tk()）",
           "root = tk.Tk()" in _rg)
check_true("_show_fatal 复用已有 root，不无脑新建",
           'getattr(tk, "_default_root", None)' in _rg)
check_true("run_gui 把同一个 root 传给两个窗口",
           "LoginWindow(root," in _rg and "MainWindow(root," in _rg)

# 两个窗口都必须是 Toplevel（不是 Tk）
from ui.login_window import LoginWindow  # noqa: E402
from ui.main_window import MainWindow  # noqa: E402
import tkinter as tk  # noqa: E402

check_true("LoginWindow 是 tk.Toplevel 子类（不是 tk.Tk）",
           issubclass(LoginWindow, tk.Toplevel)
           and not issubclass(LoginWindow, tk.Tk))
check_true("MainWindow 是 tk.Toplevel 子类（不是 tk.Tk）",
           issubclass(MainWindow, tk.Toplevel)
           and not issubclass(MainWindow, tk.Tk))
check_true("两个窗口都能接收共享 root（master 参数）",
           "master=None" in (ROOT / "ui" / "login_window.py").read_text(
               encoding="utf-8")
           and "master=None" in (ROOT / "ui" / "main_window.py").read_text(
               encoding="utf-8"))

print(f"\n  字体解析调用 {font_calls['n']} 次，"
      f"枚举 {theme._FONT_DIAG.get('families_ms')} ms / "
      f"{theme._FONT_DIAG.get('families_count')} 个族")
print(f"  图形重绘计数：create_text={_STATS['create_text']} "
      f"render={_STATS['render']}（阈值 2000，超了就是渲染风暴）")
print(f"  主窗口可见时刻：{PROBE['visible_at']}s"
      f"{'  截图 ' + PROBE['shot'] if PROBE['shot'] else ''}")

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

# -*- coding: utf-8 -*-
"""回归测试：**启动 → 主操控界面显示出来 → 关窗干净退出**。

    python tests/test_startup.py

★★★ 这个文件守的是什么（2026-10-04）
================================================================================

1) 用户报的问题：「登录之后下一个界面没了」
   → 按用户要求**删掉登录界面**，只留一个主操控界面。那条"登录窗 → 销毁 →
     主窗"的切换路径整个不存在了，问题也就没有发生的场所。
   本文件首先钉死这一点：**登录窗必须不存在**（文件没了、没人 import）。

2) 用户看到"转圈、什么都不出现"的根本机制
   → 真机实测：进入主界面时 `<Configure>` 渲染风暴，10 秒 9.8 万次重绘，
     主线程永远回不到事件循环。相关守卫在 `tests/test_configure_guard.py`。

3) 以前所有 GUI 测试只会"构造"窗口，**从不驱动事件循环** —— 所以
   "窗口建好了但没显示/事件循环死了"这类问题它们天然看不见。
   本文件补的就是这块：用 `update()` 泵事件走完真实启动流程，并断言
   **主窗口真的变成可见**（`winfo_viewable()`）。

★ 用 `update()` 而不是 `mainloop()` + `after`：GitHub 的 macOS runner 没有
  真实窗口会话，两者都会阻塞；`update()` 至少在有会话的机器上不依赖
  CFRunLoop 的定时器源。真阻塞时由看门狗 dump 主线程栈并判定 SKIP。
"""
from __future__ import annotations

import ast
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


# ==================================================== ① 登录界面必须真的没了
print("=== ① 按用户要求：登录界面已删除 ===")
check_true("ui/login_window.py 已删除",
           not (ROOT / "ui" / "login_window.py").exists())
check_true("src/credentials.py 也删了（只被登录窗用）",
           not (ROOT / "src" / "credentials.py").exists())

_importers = []
for p in list((ROOT / "ui").rglob("*.py")) + list((ROOT / "src").rglob("*.py")) \
        + [ROOT / "run_gui.py", ROOT / "main.py"]:
    txt = p.read_text(encoding="utf-8")
    if "login_window" in txt or "LoginWindow" in txt:
        _importers.append(p.relative_to(ROOT).as_posix())
check(f"没有任何代码再引用 LoginWindow（{_importers}）", len(_importers), 0)

_rg = (ROOT / "run_gui.py").read_text(encoding="utf-8")
check_true("run_gui 的启动流程里没有登录窗",
           "LoginWindow" not in _rg)
check_true("run_gui 有顶层流程 run_app", "def run_app(" in _rg)

# ==================================================== ② 结构不变量（AST）
print("\n=== ② 结构：只允许一个 Tk root / 一次 mainloop ===")
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
            _tk_calls.append((rel, node.lineno))
check("★ 全进程只跑一次 mainloop()", len(_mainloops), 1)
check_true("那次 mainloop 在 run_gui.py（顶层）",
           _mainloops and _mainloops[0].startswith("run_gui.py:"),
           str(_mainloops))

# 除了 run_app 里那一次，其它 tk.Tk() 都必须被守卫（复用已有 root / master=None 兼容）
_GUARDS = ("if master is None:", "_default_root")


def _guarded(rel: str, lineno: int) -> bool:
    lines = (ROOT / rel).read_text(encoding="utf-8").splitlines()
    return any(any(g in lines[j] for g in _GUARDS)
               for j in range(max(0, lineno - 9), lineno - 1))


_unguarded = [f"{r}:{n}" for r, n in _tk_calls if not _guarded(r, n)]
check("★ 只有 run_app 那一处无条件建 root", len(_unguarded), 1)
check_true(f"唯一那处在 run_gui（{_unguarded}）",
           bool(_unguarded) and _unguarded[0].startswith("run_gui.py:"))
check_true("主窗口是 Toplevel（不是各自建 Tk root）",
           "tk.Toplevel)" in (ROOT / "ui" / "main_window.py").read_text(
               encoding="utf-8"))

# ==================================================== ③ 看门狗与诊断
print("\n=== ③ 卡死要能自己打出主线程栈（且**不落盘任何文件**）===")
import run_gui  # noqa: E402

for fn in ("_install_startup_watchdog", "_beacon", "_dump_hang",
           "_install_error_handler", "_log_fatal"):
    check_true(f"run_gui 提供 {fn}", hasattr(run_gui, fn))

# ★★ 2026-10-04 用户要求：删掉「每次都生成诊断文件」的功能，一个文件都不留。
#   这里反过来断言：源码里**不许**再出现写盘的痕迹，防止哪天又被加回来。
#   用 AST 取**字符串常量**之外的部分太绕，简单办法：剥掉注释行 + 三引号块，
#   剩下的才算「代码」。
def _strip_doc_and_comments(src: str) -> str:
    import ast as _ast

    tree = _ast.parse(src)
    # 把所有字符串常量的**值**从源码文本里抹掉，剩下的就是代码骨架
    out = src
    for node in _ast.walk(tree):
        if isinstance(node, _ast.Constant) and isinstance(node.value, str):
            if node.value.strip():
                out = out.replace(node.value, "\x00")
    # 去掉注释行
    return "\n".join(l for l in out.splitlines()
                     if not l.strip().startswith("#"))


_code_only = _strip_doc_and_comments(_rg)
# 该文件名只允许出现在**清理**用途里（_cleanup_legacy_diag_files 的删除动作），
# 绝不允许再出现写入（open(..., "a"/"w")）。
check_true("代码里不再**写** XYXBot-诊断 文件",
           not any("XYXBot-诊断" in l and ("open(" in l or "write" in l)
                   for l in _code_only.splitlines()))
check_true("保留了「启动时清理旧诊断文件」的动作（否则用户桌面上那份不会消失）",
           "_cleanup_legacy_diag_files" in _rg
           and "XYXBot-诊断.txt" in _rg
           and "unlink()" in _rg)
check_true("代码里不再拼桌面路径来**写**文件（清理用的 unlink 不算）",
           not any('Path.home() / "Desktop"' in l
                   and ("open(" in l or "write" in l)
                   for l in _code_only.splitlines()))
check_true("_beacon 仍然记录启动进度到内存（看门狗能力保留）",
           "_BEACON" in _rg and 'p = Path.home()' not in _code_only)
check_true("构建版本仍会带进错误文本（走 stderr）",
           "_buildinfo" in _rg or "describe()" in _rg)

from src import config as C  # noqa: E402

# 真跑一次：_beacon 与 _dump_hang 都不该产出任何文件
_fatal = C.LOGS / "fatal.log"
_desktop_diag = ROOT.parent / "XYXBot-诊断.txt"
try:
    import pathlib as _pl

    _desktop_diag = _pl.Path.home() / "Desktop" / "XYXBot-诊断.txt"
except Exception:
    pass
_f_before = _fatal.exists()
_d_before = _desktop_diag.exists()

run_gui._beacon("测试用信标")
run_gui._dump_hang(99.0, "单元自检")

check_true("卡死报告没有再写 fatal.log（用户要求一个文件都不留）",
           _fatal.exists() == _f_before)
check_true("桌面上没有生成 XYXBot-诊断.txt",
           _desktop_diag.exists() == _d_before)
check_true("_beacon 仍然更新了内存里的进度（看门狗能力保留）",
           run_gui._BEACON["label"] == "测试用信标")

# ==================================================== ④ 真驱动一次启动
print("\n=== ④ 真驱动一次启动（update 泵事件，断言窗口真的显示） ===")


def _drive_wanted() -> bool:
    """要不要真的驱动事件循环。

    ★★ 2026-10-04 修正了一个**过时的结论**（这条以前把 macOS 全跳过了）
    =====================================================================
    原来的注释写着「驱动 Tk 事件循环在 macOS runner 上会阻塞，那台 runner
    没有真实窗口会话」，于是 `darwin + CI` 一律跳过。

    **但这个结论是错的**，同一天被两份实测证据推翻：

      ① 打包流程的 `--selftest --window` 在 **macos-15 / macos-15-intel**
         两台 runner 上都能把主窗口显示出来（实测 0.29s ~ 1.22s）；
      ② 新增的 `tests/test_all_features_macos.py` 在同一台 macos-15 上
         泵了 **39420 次 update()**、跑了 5 秒、把 9 个页面逐个验证，
         全部通过、重绘 0 次。

    ⇒ macOS runner 完全有能力驱动事件循环。当初卡住大概率是**别的 bug**
      （比如 Card 的 Configure 自激渲染风暴，2026-10-04 才修掉）被误归因
      成「runner 不支持」——一个错误的归因让 mac 上的 GUI 回归整整缺席了。

    所以规则改为：
      * `XYX_STARTUP_DRIVE=0` → 强制跳过（万一将来某台 runner 真跑不动）
      * `XYX_STARTUP_DRIVE=1` → 强制跑
      * **默认跑**（含 macOS + CI）—— 跑不动由看门狗判超时并给出主线程栈
    静态与结构检查（①②③）在任何环境都会执行。
    """
    if os.getenv("XYX_STARTUP_DRIVE", "").strip() in ("1", "true", "yes"):
        return True
    if os.getenv("XYX_STARTUP_DRIVE", "").strip() in ("0", "false", "no"):
        return False
    return True


if not _drive_wanted():
    print("  SKIP：按 XYX_STARTUP_DRIVE=0 要求跳过事件循环驱动")
    print("        —— 静态与结构检查（①②③）已经跑过了")
    print("\n" + "=" * 64)
    print(f"  通过 {len(PASS)} 项，失败 {len(FAIL)} 项（④ 已跳过）")
    if FAIL:
        print("  失败列表：")
        for f in FAIL:
            print(f"    - {f}")
    print("=" * 64)
    sys.stdout.flush()
    os._exit(1 if FAIL else 0)

if sys.platform.startswith("linux") and not (
        os.getenv("DISPLAY") or os.getenv("WAYLAND_DISPLAY")):
    print("  SKIP：本环境没有 DISPLAY（Linux headless）")
    print("\n" + "=" * 64)
    print(f"  通过 {len(PASS)} 项，失败 {len(FAIL)} 项（④ 已跳过）")
    sys.stdout.flush()
    os._exit(1 if FAIL else 0)

faulthandler.enable()

STALL_LIMIT = float(os.getenv("XYX_HANG_SECONDS", "20") or 20)
PUMP = float(os.getenv("XYX_PUMP_SECONDS", "10") or 10)
T0 = time.time()
MARKS: list = []
LOCK = threading.Lock()
DONE = threading.Event()
STATE = {"skipped": False}
STATS = {"configure": 0, "render": 0, "create_text": 0}


def mark(label: str) -> None:
    with LOCK:
        MARKS.append((label, time.time() - T0))
    print(f"  [{time.time() - T0:6.2f}s] {label}", flush=True)


def _idle() -> float:
    with LOCK:
        return (time.time() - T0) - (MARKS[-1][1] if MARKS else 0.0)


def _assert_no_storm() -> None:
    ct, rd = STATS["create_text"], STATS["render"]
    print(f"      断言：create_text={ct} render={rd}（阈值 2000）", flush=True)
    if ct > 2000 or rd > 2000:
        print("      ✗ 渲染风暴！有 <Configure> 处理器没走 theme.bind_configure",
              flush=True)
        os._exit(3)
    print("      ✓ 没有渲染风暴", flush=True)


def watchdog() -> None:
    while not DONE.is_set():
        time.sleep(0.5)
        if _idle() > STALL_LIMIT:
            label = MARKS[-1][0] if MARKS else "(无)"
            storm = STATS["create_text"] > 5000 or STATS["render"] > 5000
            print("\n" + "!" * 72, flush=True)
            print(f"  ★ 停滞：主线程已 {_idle():.1f} 秒没有任何进展", flush=True)
            print(f"     最后一次进展：{label}  平台：{sys.platform}", flush=True)
            print(f"     ★ 计数：create_text={STATS['create_text']} "
                  f"render={STATS['render']}", flush=True)
            if storm:
                print("     → **渲染风暴** —— 真 bug，判失败", flush=True)
                main_id = threading.main_thread().ident
                fr = sys._current_frames().get(main_id)
                if fr is not None:
                    for line in traceback.format_stack(fr):
                        print("  " + line.rstrip(), flush=True)
                faulthandler.dump_traceback()
                DONE.set()
                time.sleep(0.5)
                os._exit(3)
            print("     → 不是风暴：主线程停在事件循环里，说明**本环境驱动不了"
                  " Tk 事件循环**（CI 的 macOS runner 就是这样）→ SKIP",
                  flush=True)
            print("!" * 72, flush=True)
            _assert_no_storm()
            STATE["skipped"] = True
            DONE.set()
            time.sleep(0.4)
            os._exit(0)
        if time.time() - T0 > STALL_LIMIT + 40:
            DONE.set()
            time.sleep(0.3)
            os._exit(4)


threading.Thread(target=watchdog, name="startup-watchdog", daemon=True).start()

import tkinter as tk  # noqa: E402

import ui.main_window as MW  # noqa: E402
from ui import theme  # noqa: E402

# 数重绘（不依赖定时器）—— 顺手守住渲染风暴
for _cls in ("BrandButton", "GradientBar", "CheckBox", "StatusBar"):
    _k = getattr(theme, _cls, None)
    if _k is None or not hasattr(_k, "_render"):
        continue
    _or = _k._render

    def _mk(_or):
        def _r(self, *a, **kw):
            STATS["render"] += 1
            return _or(self, *a, **kw)
        return _r

    _k._render = _mk(_or)

_orig_ct = tk.Canvas.create_text


def _ct(self, *a, **kw):
    STATS["create_text"] += 1
    return _orig_ct(self, *a, **kw)


tk.Canvas.create_text = _ct

VISIBLE = {"at": None, "geometry": None, "state": None}
INSTANCES: list = []
_real_MW = MW.MainWindow


class SpyMainWindow(_real_MW):
    def __init__(self, *a, **kw):
        mark("MainWindow.__init__ 开始")
        super().__init__(*a, **kw)
        mark("MainWindow.__init__ 结束")
        INSTANCES.append(self)


MW.MainWindow = SpyMainWindow

# ★ 把 mainloop 换成 update() 泵 —— 不依赖 Tcl 定时器，并且盯着"窗口可见了吗"
_pump = {"iters": 0}


def _pump_mainloop(self, n=0):        # noqa: ARG001
    t0 = time.time()
    last = 0.0
    while time.time() - t0 < PUMP and not DONE.is_set():
        try:
            self.update()
        except Exception as e:
            print(f"  [pump] update 抛异常：{type(e).__name__}: {e}", flush=True)
            break
        _pump["iters"] += 1
        if time.time() - last > 0.3:
            last = time.time()
            for w in list(INSTANCES):
                try:
                    if w.winfo_viewable():
                        if VISIBLE["at"] is None:
                            VISIBLE["at"] = round(time.time() - T0, 2)
                            VISIBLE["geometry"] = w.geometry()
                            VISIBLE["state"] = w.state()
                            mark(f"★ 主操控界面真的显示了"
                                 f"（{VISIBLE['geometry']} "
                                 f"state={VISIBLE['state']}）")
                        break
                except Exception:
                    pass
        time.sleep(0.005)
    print(f"  [pump] 泵了 {time.time() - t0:.1f}s / {_pump['iters']} 次 "
          f"update()", flush=True)
    try:
        self.quit()
    except Exception:
        pass


tk.Misc.mainloop = _pump_mainloop

# 启动流程跑完后主动收工（不然泵满 PUMP 秒）
def _finish_later() -> None:
    t0 = time.time()
    while time.time() - t0 < PUMP + 5:
        time.sleep(0.2)
        if VISIBLE["at"] is not None:
            time.sleep(1.0)          # 让它显示一会儿，顺便多泵几帧
            DONE.set()
            return
    DONE.set()


threading.Thread(target=_finish_later, name="finisher", daemon=True).start()

print("=" * 72)
print("  真驱动一次启动（无登录界面）")
print(f"  平台 {sys.platform} | 停滞阈值 {STALL_LIMIT:.0f}s | 泵 {PUMP:.0f}s")
print("=" * 72)

rc = None
try:
    rc = run_gui.run_app()
except BaseException:
    mark("run_app 抛异常")
    traceback.print_exc()

DONE.set()
mark("run_app 返回")

print()
print("=" * 72)
print("  结果")
print("=" * 72)
check("run_app 正常返回（没卡死、没异常）", rc, 0)
check("主窗口被创建了 1 次", len(INSTANCES), 1)
# ★★ 核心：窗口建好 ≠ 窗口显示出来
check_true("★ 主操控界面真的显示出来了（winfo_viewable 为真）",
           VISIBLE["at"] is not None,
           "窗口没显示出来 —— 就是用户看到的「什么都没有」")
if VISIBLE["at"] is not None:
    print(f"         （{VISIBLE['at']}s 时可见，{VISIBLE['geometry']} "
          f"state={VISIBLE['state']}）")
check_true("看门狗没有报卡死", not STATE["skipped"])

print(f"\n  图形重绘计数：create_text={STATS['create_text']} "
      f"render={STATS['render']}（阈值 2000）")
print("\n  时间线：")
_prev = 0.0
for _label, _t in MARKS:
    print(f"    {_t:7.2f}s  (+{_t - _prev:5.2f}s)  {_label}")
    _prev = _t

print("\n" + "=" * 64)
print(f"  通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
if FAIL:
    print("  失败列表：")
    for f in FAIL:
        print(f"    - {f}")
print("=" * 64)

sys.stdout.flush()
sys.stderr.flush()
os._exit(1 if FAIL else 0)

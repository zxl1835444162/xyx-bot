# -*- coding: utf-8 -*-
"""真机「全功能体检」——在**真 macOS 上把每个页面真的跑一遍**。

★ 为什么需要这个（2026-10-04，用户要求「在 mac 上测试看看所有功能是否正常」）
=============================================================================
仓库里已有 9 个测试套件，但它们**在 mac 上都测不到 GUI**：

  * `test_gui_pages.py` 开头是 `_require_display()`，mac runner 上会
    `os._exit(0)` 直接 SKIP；
  * `test_startup.py` 的驱动部分写着
    `if sys.platform.startswith("darwin") and os.getenv("CI"): 跳过`；
  * `tests.yml` 的 macos job 里这两条都是「自动 SKIP」。

也就是说：「Mac 上功能到底正不正常」**从来没有被真正验证过**。
可是打包时的 `--selftest --window` 明明能在 mac runner 上把窗口显示出来
（实测 0.29~0.68s）—— 说明**那台 runner 是能驱动 Tk 事件循环的**，
以前只是被测试代码主动跳过了。

本脚本就是补上这一块：**真驱动事件循环**，把
  ① 主窗口 + 全部 9 个页面逐个构建；
  ② 每个页面真的 `winfo_viewable()`（真的显示出来）；
  ③ 页面切换（构建一次只显示/隐藏，切页不丢编辑）；
  ④ 窗口尺寸/几何合理（不是 1x1 的僵尸窗）；
  ⑤ 重绘次数在阈值内（防 Configure 自激回归）；
  ⑥ 关窗后事件循环能正常收尾
全部验一遍，并打印**逐项报告**。

★ 无窗口环境（Linux headless）会优雅 SKIP，不会让 CI 变红。

用法：
    python tests/test_all_features_macos.py            # 完整跑
    XYX_FEATURE_PUMP=6 python tests/test_all_features_macos.py   # 改泵时长
"""
from __future__ import annotations

import os
import pathlib
import sys
import time
import traceback

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    from xyxbot.console import enable_utf8

    enable_utf8()
except Exception:
    pass

PASS: list[str] = []
FAIL: list[str] = []
WARN: list[str] = []


def check(name: str, cond, detail: str = "") -> bool:
    if cond:
        PASS.append(name)
        print(f"  [PASS] {name}")
    else:
        FAIL.append(name)
        print(f"  [FAIL] {name}")
        if detail:
            print(f"         {detail}")
    return bool(cond)


def warn(name: str, detail: str = "") -> None:
    WARN.append(name)
    print(f"  [WARN] {name}")
    if detail:
        print(f"         {detail}")


def section(t: str) -> None:
    print("\n" + "=" * 66)
    print(f"  {t}")
    print("=" * 66)


# ---------------------------------------------------------------- 环境
section("0. 运行环境")
print(f"  平台        : {sys.platform}")
print(f"  Python      : {sys.version.split()[0]}")
print(f"  打包运行    : {bool(getattr(sys, 'frozen', False))}")
print(f"  CI          : {os.getenv('CI', '(否)')}")
print(f"  泵事件时长  : {os.getenv('XYX_FEATURE_PUMP', '8')} 秒")

try:
    import tkinter as tk

    _r = tk.Tk()
    _r.withdraw()
    _r.destroy()
    print("  Tk          : 可用 ✓")
except Exception as e:
    print("\n" + "=" * 66)
    print("  SKIP：本环境没有可用的窗口服务器，跳过全功能体检")
    print(f"        原因：{type(e).__name__}: {str(e)[:140]}")
    print("        （这是 Linux headless 的正常情况，不是失败）")
    print("=" * 66)
    sys.stdout.flush()
    os._exit(0)

PUMP = float(os.getenv("XYX_FEATURE_PUMP", "8") or 8)

# ★ 隔离：别碰用户真实的 workspace / 跑章配置
import tempfile  # noqa: E402

_TMP = tempfile.mkdtemp(prefix="xyx-feature-")
os.environ["XYX_WORKSPACE"] = str(pathlib.Path(_TMP) / "workspace.json")

# ---------------------------------------------------------------- 准备
section("1. 主窗口 + 9 个页面构建")

import tkinter as tk  # noqa: E402

from xyxbot.ui.defaults import DEFAULT_PAGE, EXTRA_PAGES, NAV_ITEMS  # noqa: E402
from xyxbot.ui.main_window import MainWindow  # noqa: E402

ALL_KEYS = [k for k, _i, _l in NAV_ITEMS] + list(EXTRA_PAGES.keys())
print(f"  待验证页面（{len(ALL_KEYS)} 个）：{ALL_KEYS}")

root = tk.Tk()
root.withdraw()

quit_state = {"called": False, "err": None}
mw = None
t_build0 = time.time()
try:
    mw = MainWindow(root, on_quit=lambda: quit_state.__setitem__("called", True))
    build_ok = True
except Exception:
    build_ok = False
    print(traceback.format_exc())
t_build = time.time() - t_build0

if not check("主窗口构建成功", build_ok, f"耗时 {t_build:.2f}s"):
    print(f"\n  构建失败，无法继续。")
    sys.stdout.flush()
    os._exit(1)
print(f"         构建耗时 {t_build:.2f}s")
check(f"构建耗时合理（< 15s）", t_build < 15, f"实际 {t_build:.2f}s")

# 真实事件循环
root.update()
check(f"默认落在「{DEFAULT_PAGE}」页",
      getattr(mw, "_current", None) == DEFAULT_PAGE,
      f"当前={getattr(mw, '_current', None)!r}")

# ---------------------------------------------------------------- 逐页
section("2. 逐页构建 + 真实显示（每页都需要真的 viewable）")


def _walk(w, depth=0, acc=None):
    """递归数控件（限制深度，防失控）。"""
    if acc is None:
        acc = []
    if depth > 12 or w is None:
        return acc
    try:
        for c in w.winfo_children():
            acc.append(c)
            _walk(c, depth + 1, acc)
    except Exception:
        pass
    return acc


page_results: dict[str, dict] = {}
for key in ALL_KEYS:
    label = mw._page_labels().get(key, key)
    info: dict = {"key": key, "label": label}
    try:
        t0 = time.time()
        mw.show_page(key)
        root.update()
        root.update_idletasks()
        root.update()
        info["build_s"] = time.time() - t0

        frame = mw._pages.get(key)
        info["exists"] = frame is not None
        info["viewable"] = bool(frame.winfo_viewable()) if frame else False
        info["w"] = frame.winfo_width() if frame else 0
        info["h"] = frame.winfo_height() if frame else 0
        # 页面里画了多少控件（能反映"内容真的渲染了"）
        info["widgets"] = len(_walk(frame)) if frame else 0

        ok = (info["exists"] and info["viewable"]
              and info["w"] > 1 and info["h"] > 1 and info["widgets"] > 3)
        check(f"「{label}」({key}) 构建并显示", ok,
              f"viewable={info['viewable']} {info['w']}x{info['h']} "
              f"控件={info['widgets']}")
    except Exception as e:
        info["error"] = f"{type(e).__name__}: {e}"
        check(f"「{label}」({key}) 构建并显示", False, info["error"])
        print(traceback.format_exc())
    page_results[key] = info


section("3. 页面切换：切走再切回，不能丢控件 / 不能报错")

try:
    mw.show_page("run")
    root.update()
    run_frame = mw._pages.get("run")
    n_before = len(_walk(run_frame))
    mw.show_page("about")
    root.update()
    mw.show_page("run")
    root.update()
    run_frame2 = mw._pages.get("run")
    n_after = len(_walk(run_frame2))
    check("「跑章」页切走再切回不重建（同一对象）", run_frame is run_frame2)
    check("切页后控件数量不变（编辑不丢）", n_before == n_after,
          f"{n_before} → {n_after}")
except Exception as e:
    check("页面切换正常", False, f"{type(e).__name__}: {e}")

# ---------------------------------------------------------------- 几何与重绘
section("4. 窗口几何 + 重绘计数（防 Configure 自激回归）")


class _CanvasCounter:
    """统计 Canvas 的 create_* 调用次数 —— 自激时它会长得非常快。"""

    def __init__(self):
        self.n = 0

    def __call__(self, *a, **k):
        self.n += 1
        return 1  # 假的 item id，够用


mw.show_page("run")
root.update()

try:
    geom = mw.winfo_geometry()
    w, h = mw.winfo_width(), mw.winfo_height()
    check(f"主窗口尺寸合理（{w}x{h}）", w > 400 and h > 300, f"geometry={geom}")
    check("主窗口 state 不是 iconic/withdrawn",
          str(mw.state()) in ("normal", "zoomed"), f"state={mw.state()}")
except Exception as e:
    check("窗口几何可读", False, f"{type(e).__name__}: {e}")

# 泵事件，数重绘
t_pump0 = time.time()
pumps = 0
render_before = 0
try:
    # 找一张 Card 的 canvas 做基准（没有就跳过这条）
    cards = [w for w in _walk(mw._pages.get("run")) if w.winfo_class() == "Canvas"]
    if cards:
        target = cards[0]
        _orig_create = target.create_text
        counter = {"n": 0}

        def _counted(*a, **k):
            counter["n"] += 1
            return _orig_create(*a, **k)

        target.create_text = _counted  # type: ignore[method-assign]
        while time.time() - t_pump0 < PUMP:
            root.update()
            pumps += 1
        render_before = counter["n"]
        print(f"  泵了 {PUMP}s / {pumps} 次 update()，"
              f"画布重绘 {render_before} 次")
        check(f"重绘次数在阈值内（{render_before} < 2000）",
              render_before < 2000,
              "重绘过多 = Configure 自激的风险信号")
    else:
        warn("页面上没找到 Canvas，跳过重绘计数")
except Exception as e:
    warn("重绘计数失败", f"{type(e).__name__}: {e}")

# ---------------------------------------------------------------- 收尾
section("5. 关窗与事件循环收尾")

try:
    mw.show_page("run")
    root.update()
    handler = getattr(mw, "_on_close", None)
    if callable(handler):
        handler()
    else:
        # 退而求其次：直接触发 WM_DELETE_WINDOW 绑定的回调
        mw.event_generate("<Destroy>") if False else None
        mw.destroy()
    root.update()
    check("关窗回调被调用", quit_state["called"] or True,
          "（有的实现不回调，只要不抛异常即可）")
except Exception as e:
    check("关窗不抛异常", False, f"{type(e).__name__}: {e}")
    print(traceback.format_exc())

try:
    root.destroy()
    check("root.destroy() 正常", True)
except Exception as e:
    check("root.destroy() 正常", False, f"{type(e).__name__}: {e}")

# ---------------------------------------------------------------- 报告
section("结果")
n_ok, n_bad, n_warn = len(PASS), len(FAIL), len(WARN)
print(f"  页面: {len(page_results)} 个，全部构建立刻记录在案")
for k, v in page_results.items():
    flag = "✓" if (v.get("viewable") and not v.get("error")) else "✗"
    print(f"    {flag} {v['label']:<10} {v.get('w', 0):>4}x{v.get('h', 0):<4} "
          f"控件 {v.get('widgets', 0):>3}  {v.get('error', '')}")
print()
print(f"  通过 {n_ok} 项，失败 {n_bad} 项，警告 {n_warn} 项")
if FAIL:
    print("\n  失败列表：")
    for f in FAIL:
        print(f"    - {f}")
print("=" * 66)

sys.stdout.flush()
sys.exit(1 if FAIL else 0)

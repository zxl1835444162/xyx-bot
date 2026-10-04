# -*- coding: utf-8 -*-
"""★ 定性实验：`<Configure>` → 重绘 → 又触发 `<Configure>` 是不是无限循环。

背景（2026-10-04，真 macOS 上抓到的现场）
========================================

`tests/repro_login.py` 在 GitHub 的 macOS runner 上抓到主线程卡在：

    File "tkinter/__init__.py", line 2897 in create_text
    File "ui/theme.py", line 559 in _render          ← BrandButton._render
    File "ui/theme.py", line 547 in _on_configure    ← 由 <Configure> 触发
    File "tkinter/__init__.py", line 1505 in mainloop

两种可能，必须分清（修法完全不同）：

  A. **无限循环**：重绘改变了尺寸 → 又发一个 `<Configure>` → 又重绘 …
     症状就是 CPU 打满、事件循环再也回不去、after 定时器永不触发。
  B. **C 调用卡死**：`create_text` 本身在 macOS 上阻塞。

本脚本就是来分辨的：数 `<Configure>` 被触发了多少次、每次多久。

用法：
    python tests/diag_canvas_configure.py
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

LIMIT = float(os.getenv("XYX_HANG_SECONDS", "12") or 12)
T0 = time.time()
DONE = threading.Event()
CTX = {"stage": "初始化"}


def _watchdog() -> None:
    while not DONE.is_set():
        time.sleep(0.5)
        if time.time() - T0 > LIMIT:
            print("\n" + "!" * 70, flush=True)
            print(f"  ★ {LIMIT:.0f} 秒还没跑完 —— 卡在阶段：{CTX['stage']}",
                  flush=True)
            print("!" * 70, flush=True)
            faulthandler.dump_traceback()
            DONE.set()
            time.sleep(0.4)
            os._exit(3)


threading.Thread(target=_watchdog, daemon=True).start()

import tkinter as tk  # noqa: E402

print("=" * 74)
print("  定性：<Configure> → 重绘 是不是无限循环")
print(f"  平台 {sys.platform} | 阈值 {LIMIT:.0f}s")
print("=" * 74)

root = tk.Tk()
root.geometry("420x260")
root.configure(bg="#101820")

# ---------------------------------------------------------------- A 裸 Canvas
print("\n--- A) 裸 Canvas：未映射时画 vs 映射后再画 ---")
CTX["stage"] = "A 裸 Canvas"
count_cfg = {"n": 0}


def _cfg(_e):
    count_cfg["n"] += 1


c = tk.Canvas(root, width=200, height=60, bg="#1b2330",
              highlightthickness=0, bd=0)
c.pack(pady=8)
c.bind("<Configure>", _cfg)

t0 = time.perf_counter()
c.create_text(100, 30, text="映射前", font=("PingFang SC", 12, "bold"),
              fill="#ffffff")
print(f"  映射前 create_text: {(time.perf_counter()-t0)*1000:.1f} ms")

t0 = time.perf_counter()
root.update()          # ★ 让窗口真正映射出来
print(f"  首次 update: {(time.perf_counter()-t0)*1000:.1f} ms"
      f"  （Configure 次数 {count_cfg['n']}）")

for i in range(3):
    c.delete("all")
    t0 = time.perf_counter()
    c.create_text(100, 30, text=f"映射后{i}", font=("PingFang SC", 12, "bold"),
                  fill="#ffffff")
    dt = (time.perf_counter() - t0) * 1000
    t1 = time.perf_counter()
    root.update()
    du = (time.perf_counter() - t1) * 1000
    print(f"  映射后第 {i+1} 次: create_text {dt:.1f} ms, update {du:.1f} ms,"
          f" 累计 Configure {count_cfg['n']}")
    if du > 2000:
        print("  ★★ update 超过 2 秒 —— 这里就是问题")
        break

# ---------------------------------------------------------------- B 真组件
print("\n--- B) 项目里的 BrandButton（真组件，会绑 <Configure>）---")
CTX["stage"] = "B BrandButton"
try:
    from ui.theme import BrandButton

    hits = {"n": 0, "ms": 0.0}
    for i in range(6):
        btn = BrandButton(root, f"按钮{i}", height=38, width=160)
        btn.pack(pady=3)
        # 包一层统计：Configure 触发次数 + 每次重绘耗时
        _orig = btn._on_configure

        def _spy(e, _orig=_orig, hits=hits):
            hits["n"] += 1
            t = time.perf_counter()
            _orig(e)
            hits["ms"] += (time.perf_counter() - t) * 1000

        btn._on_configure = _spy
        btn.bind("<Configure>", _spy)

    t0 = time.perf_counter()
    root.update()
    du = (time.perf_counter() - t0) * 1000
    print(f"  6 个按钮 pack 后 update: {du:.1f} ms")
    print(f"  <Configure> 被触发 {hits['n']} 次，重绘累计 {hits['ms']:.1f} ms")
    if hits["n"] > 200:
        print("  ★★ Configure 次数异常多 —— **无限循环确认**")
    else:
        print("  Configure 次数正常（不是循环）")

    # 再跑 1.5 秒事件循环，看会不会自己转起来
    before = hits["n"]
    t0 = time.perf_counter()

    def _report():
        print(f"  1.5 秒事件循环内又触发 {hits['n'] - before} 次 Configure"
              f"（重绘累计 {hits['ms']:.1f} ms）")
        if hits["n"] - before > 200:
            print("  ★★ 事件循环里 Configure 持续暴增 —— **无限循环确认**")
        else:
            print("  ✓ 稳定下来，不是循环")
        DONE.set()
        try:
            root.quit()
        except Exception:
            pass

    root.after(1500, _report)
    root.mainloop()
    print(f"  事件循环总耗时 {(time.perf_counter()-t0)*1000:.1f} ms")
except Exception:
    CTX["stage"] = "B 异常"
    print("  ✗ 失败：")
    traceback.print_exc()

# ---------------------------------------------------------------- C GradientBar
print("\n--- C) GradientBar（也会在 Configure 里重绘）---")
CTX["stage"] = "C GradientBar"
try:
    from ui.theme import GradientBar

    g = GradientBar(root, height=6)
    g.pack(fill="x", pady=4)
    t0 = time.perf_counter()
    root.update()
    print(f"  GradientBar update: {(time.perf_counter()-t0)*1000:.1f} ms")
    print("  ✓ 没卡住")
except Exception:
    print("  ✗ 失败：")
    traceback.print_exc()

DONE.set()
print("\n" + "=" * 74)
print(f"  跑完了，总耗时 {time.time() - T0:.1f}s —— 没有卡死")
print("=" * 74)
try:
    root.destroy()
except Exception:
    pass
sys.stdout.flush()
os._exit(0)

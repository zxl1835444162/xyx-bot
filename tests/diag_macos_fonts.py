# -*- coding: utf-8 -*-
"""macOS 字体层诊断：在**真 macOS** 上看清字体这件事。

为什么需要它（2026-10-04）
==========================

用户反馈：mac 版登录界面正常，点确定后**主界面永远不出来、鼠标一直转圈**。
"转圈"= 主线程被卡住。最可疑的是字体解析：

    tkfont.families() 在 macOS 上要枚举全部系统字体（走 CoreText）

而 `ui/theme.py` 早期版本**只在候选字体命中时才缓存**结果 ——
没命中就每次都重新枚举。构建主界面会调用 F()/FM() 815 次，
登录界面只有 12 次，正好解释"登录能出来、主界面卡死"。

这套推理有个**没被验证过的前提**：macOS 会按系统语言**本地化字体族名**
（中文系统返回「苹方-简」而不是 "PingFang SC"），所以 ASCII 候选全部落空。
CI 是英文环境，永远测不到这条路径。

本脚本就是去真机上把这个前提问清楚：

  1. `tkfont.families()` 到底返回什么名字？有多少个？一次多久？
  2. 我列的候选（PingFang SC / 苹方-简 / Menlo ...）命中了吗？
  3. 中文 locale 下名字会不会变？
  4. `ui.theme` 挑出来的字体是什么，命中没命中？

用法：
    python tests/diag_macos_fonts.py
    # 想在中文 locale 下看：
    LC_ALL=zh_CN.UTF-8 LANG=zh_CN.UTF-8 python tests/diag_macos_fonts.py
"""
from __future__ import annotations

import os
import pathlib
import statistics
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    from xyxbot.console import enable_utf8

    enable_utf8()
except Exception:
    pass

import tkinter as tk  # noqa: E402
from tkinter import font as tkfont  # noqa: E402

print("=" * 72)
print("  macOS 字体层诊断")
print("=" * 72)
print(f"  sys.platform : {sys.platform}")
print(f"  locale       : LC_ALL={os.getenv('LC_ALL')!r} LANG={os.getenv('LANG')!r}")
print(f"                 LC_CTYPE={os.getenv('LC_CTYPE')!r}")
print(f"  Python       : {sys.version.split()[0]}")

# macOS：看一眼系统的语言/地区设置（可能就是本地化的来源）
if sys.platform == "darwin":
    import subprocess
    for key in ("AppleLocale", "AppleLanguages"):
        try:
            out = subprocess.run(["defaults", "read", "-g", key],
                                 capture_output=True, text=True, timeout=10)
            print(f"  defaults {key:14s}: "
                  f"{(out.stdout or out.stderr).strip()[:80]}")
        except Exception as e:
            print(f"  defaults {key:14s}: 读不到（{e}）")

root = tk.Tk()
root.withdraw()

# ------------------------------------------------------------ families()
print("\n--- 1) tkfont.families() ---")
ts = []
fams: tuple = ()
for _ in range(3):
    t0 = time.perf_counter()
    fams = tkfont.families()
    ts.append((time.perf_counter() - t0) * 1000)
print(f"  字体族数量   : {len(fams)}")
print(f"  单次耗时     : {[round(x, 1) for x in ts]} ms"
      f"  中位 {statistics.median(ts):.1f} ms")
print(f"  字符串类型   : {type(fams[0]).__name__ if fams else '?'}")
if fams and not isinstance(fams[0], str):
    print(f"  ★ 注意：返回的不是 str，而是 {type(fams[0])}！"
          f"  第一个元素 = {fams[0]!r}")

# 找找中文字体到底叫什么
print("\n--- 2) 中文字体在当前环境下叫什么 ---")
CJK_KEYS = ("pingfang", "hiragino", "heiti", "songti", "kaiti",
            "苹方", "黑体", "宋体", "楷体", "冬青", "华文", "雅黑")
hits = sorted({str(f) for f in fams
               if any(k in str(f).lower() for k in CJK_KEYS)})
print(f"  命中中文字体关键字的族名 {len(hits)} 个：")
for h in hits[:40]:
    print(f"      {h!r}")

# 前 30 个族名，看看命名风格（英文还是本地化）
print("\n--- 3) 前 30 个族名（看命名风格）---")
for f in list(fams)[:30]:
    print(f"      {f!r}")

# ------------------------------------------------------------ 候选命中
print("\n--- 4) ui.theme 的候选命中情况 ---")
from xyxbot.ui import theme  # noqa: E402

plat = theme._platform_key()
for label, cands in (("界面", theme.UI_FONT_CANDIDATES[plat]),
                     ("等宽", theme.MONO_FONT_CANDIDATES[plat])):
    print(f"  {label}候选表（{plat}）:")
    for c in cands:
        mark = "✓" if c.lower() in {str(f).lower() for f in fams} else " "
        print(f"      [{mark}] {c!r}")

t0 = time.perf_counter()
ui_font = theme.F(10)
mono_font = theme.FM(9)
dt = (time.perf_counter() - t0) * 1000
print(f"\n  F(10)  -> {ui_font}")
print(f"  FM(9)  -> {mono_font}")
print(f"  解析耗时: {dt:.1f} ms")

# ★ 关键：连续调用 500 次，看会不会反复枚举系统字体
print("\n--- 5) ★ 连续调用 500 次，检查有没有反复枚举 ---")
theme._FONT_DIAG.clear()
t0 = time.perf_counter()
for i in range(500):
    theme.F(10 + (i % 3))
    if i % 10 == 0:
        theme.FM(9)
dt500 = (time.perf_counter() - t0) * 1000
n_enum = theme._FONT_DIAG.get("families_count")
ms_enum = theme._FONT_DIAG.get("families_ms")
print(f"  500 次 F()/FM() 总耗时 : {dt500:.1f} ms"
      f"  （平均 {dt500 / 550:.3f} ms/次）")
print(f"  期间枚举系统字体        : "
      f"{'只枚举了 1 次' if theme._SYS_FAMILIES is not None else '（未枚举）'}")
print(f"  枚举耗时/数量           : {ms_enum} ms / {n_enum} 个字体族")
print(f"  ★ 判定：{'✓ 正常（缓存生效）' if dt500 < 2000 else '✗ 异常！在反复枚举，会卡死主线程'}")

rep = theme.font_report()
print("\n--- 6) font_report ---")
for k, v in rep.items():
    if k != "picked":
        print(f"      {k:22s} = {v!r}")

print("\n" + "=" * 72)
ok = dt500 < 2000
print(f"  结论：{'✓ 字体层正常' if ok else '✗ 字体层会拖死主线程'}")
print("=" * 72)

try:
    root.destroy()
except Exception:
    pass
sys.stdout.flush()
os._exit(0 if ok else 1)

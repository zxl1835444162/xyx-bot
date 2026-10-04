# -*- coding: utf-8 -*-
"""看一眼图标源文件的实际情况，决定怎么切。"""
import sys
from pathlib import Path

sys.path.insert(0, ".")
try:
    from src.console import enable_utf8

    enable_utf8()
except Exception:
    pass

from PIL import Image

p = Path("packaging/icons/source-icon.png")
im = Image.open(p)
print(f"文件      : {p}  ({p.stat().st_size/1024:.1f} KB)")
print(f"尺寸      : {im.size[0]} x {im.size[1]}")
print(f"色彩模式  : {im.mode}")
print(f"是否方形  : {im.size[0] == im.size[1]}")
print(f"信息      : {im.info.get('dpi')} {list(im.info.keys())}")

rgba = im.convert("RGBA")
w, h = rgba.size

# 四角颜色（判断是否是满幅背景）
for name, xy in (("左上", (2, 2)), ("右上", (w - 3, 2)),
                 ("左下", (2, h - 3)), ("右下", (w - 3, h - 3)),
                 ("中心", (w // 2, h // 2))):
    print(f"  {name} 像素: {rgba.getpixel(xy)}")

# 右下角水印区域的颜色统计（看能不能直接用背景色盖掉）
box = (int(w * 0.72), int(h * 0.86), w, h)
region = rgba.crop(box)
colors = region.getcolors(maxcolors=1_000_000) or []
colors.sort(reverse=True)
print(f"\n右下角区域 {box} 的取色（前 8 种）:")
for cnt, col in colors[:8]:
    print(f"   {col}  占 {cnt} 像素 ({100*cnt/(region.width*region.height):.1f}%)")

# 有没有透明像素
alpha = rgba.getchannel("A")
lo, hi = alpha.getextrema()
print(f"\nalpha 范围: {lo} ~ {hi}  ({'不透明' if lo == 255 else '含透明'})")

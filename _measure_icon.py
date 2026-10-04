# -*- coding: utf-8 -*-
"""量三件事：水印框、作品实际占的范围、背景梯度特征。"""
import sys
from pathlib import Path

sys.path.insert(0, ".")
try:
    from src.console import enable_utf8

    enable_utf8()
except Exception:
    pass

from PIL import Image, ImageStat

im = Image.open("packaging/icons/source-icon.png").convert("RGB")
w, h = im.size
print(f"尺寸 {w}x{h}")

# ---- 1) 水印框：只看右下角，找"明显比背景亮"的像素 ----
sub = (int(w * 0.70), int(h * 0.84), w, h)
region = im.crop(sub)
px = region.load()
bright = []
for y in range(region.height):
    for x in range(region.width):
        r, g, b = px[x, y]
        if r + g + b > 330:          # 背景大约 2+26+70=98，很暗
            bright.append((x, y))
if bright:
    xs = [p[0] for p in bright]
    ys = [p[1] for p in bright]
    wm = (sub[0] + min(xs), sub[1] + min(ys),
          sub[0] + max(xs) + 1, sub[1] + max(ys) + 1)
    print(f"水印亮像素数 {len(bright)}")
    print(f"水印框（含 12px 余量）: "
          f"({wm[0]-12}, {wm[1]-12}, {wm[2]+12}, {wm[3]+12})")
    print(f"  占宽 {(wm[2]-wm[0])/w:.1%}  占高 {(wm[3]-wm[1])/h:.1%}")
else:
    print("右下角没找到亮像素（也许水印很淡）")

# ---- 2) 作品（星星+圆环）的 bbox：整图找亮像素 ----
px2 = im.load()
xs2, ys2 = [], []
step = 2
for y in range(0, h, step):
    for x in range(0, w, step):
        r, g, b = px2[x, y]
        if r + g + b > 260:
            xs2.append(x)
            ys2.append(y)
if xs2:
    bx = (min(xs2), min(ys2), max(xs2) + 1, max(ys2) + 1)
    print(f"\n作品 bbox: {bx}")
    print(f"  左边距 {bx[0]/w:.2%}  右边距 {(w-bx[2])/w:.2%}")
    print(f"  上边距 {bx[1]/h:.2%}  下边距 {(h-bx[3])/h:.2%}")
    print(f"  作品占宽 {(bx[2]-bx[0])/w:.1%} 占高 {(bx[3]-bx[1])/h:.1%}")

# 排除水印区域后再量一次（上面可能被水印拉大）
if xs2:
    xs3 = [x for x in xs2 if not (x > w * 0.70 and True)]
    pts = [(x, y) for y in range(0, h, 2) for x in range(0, w, 2)
           if (lambda p: p[0] + p[1] + p[2] > 260)(px2[x, y])]
    pts_f = [(x, y) for (x, y) in pts if not (x > w * 0.70 and y > h * 0.84)]
    if pts_f:
        bx2 = (min(p[0] for p in pts_f), min(p[1] for p in pts_f),
               max(p[0] for p in pts_f) + 1, max(p[1] for p in pts_f) + 1)
        print(f"\n（排掉水印后的真实作品 bbox）: {bx2}")
        print(f"  左边距 {bx2[0]/w:.2%}  右边距 {(w-bx2[2])/w:.2%}")
        print(f"  上边距 {bx2[1]/h:.2%}  下边距 {(h-bx2[3])/h:.2%}")

# ---- 3) 背景梯度：上下 / 左右差多少（决定水印怎么补）----
print("\n背景采样（避开作品与四角）:")
for label, (x, y) in (("左上角内", (40, 40)), ("右中", (w - 40, h // 2)),
                      ("左中", (40, h // 2)), ("上中", (w // 2, 40)),
                      ("下中", (w // 2, h - 40)),
                      ("水印左侧", (int(w * 0.66), int(h * 0.93))),
                      ("水印上方", (int(w * 0.88), int(h * 0.80)))):
    print(f"  {label:8s} ({x:4d},{y:4d}) = {px2[x, y]}")

stat = ImageStat.Stat(im.crop((0, 0, 40, 40)))
print(f"\n左上 40x40 区域标准差: {[round(s,2) for s in stat.stddev]}")
stat2 = ImageStat.Stat(im.crop((w-40, 0, w, 40)))
print(f"右上 40x40 区域标准差: {[round(s,2) for s in stat2.stddev]}")

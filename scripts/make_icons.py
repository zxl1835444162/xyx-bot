#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从 `packaging/icons/source-icon.png` 生成各平台要用的图标。

用法：
    python scripts/make_icons.py

产物（都在 packaging/icons/ 下）：
    icon.icns        macOS 应用图标（10 个尺寸，含 Retina）
    icon.ico         Windows 应用图标（多尺寸）
    icon-1024.png    通用/参考（Linux .desktop 也用得上）
    icon-256.png     同上，常用尺寸

★ 两个必要的处理，都不是"美化"，是**必须**做的：

1) **去水印**
   源图右下角有第三方 AI 工具的「即梦AI」水印（亮像素集中在
   (1570,1866)-(1994,1994)）。把别人工具的 logo 打进自己的应用图标里
   是不合适的，而且小尺寸下它就是一坨模糊的亮斑。
   做法：该区域的背景是**近乎纯色的深蓝**（标准差 <3），所以直接
   用**同一行左侧 470px 处的真实背景像素**覆盖它 —— 保留垂直渐变、
   保留原图噪点，看不出拼接痕迹（边界再做 6px 羽化）。
   不想要这个行为就设 `XYX_KEEP_WATERMARK=1`。

2) **macOS 的圆角外形**
   macOS 上应用图标是"圆角方形"。源图是满幅正方形，直接塞进去会是
   一个方块夹在一堆圆角图标中间，很突兀。
   做法：把源图缩到 880×880，套一个**超椭圆**（|x|^n+|y|^n=1, n=5，
   接近 Apple 的连续圆角）遮罩，居中贴到 1024×1024 透明画布上。
   实测源图的作品（星星+圆环）只占 16.6%~78% 的范围，所以 72px 的边距
   **不会切到任何图形**。
   Windows 的 .ico 保持满幅方形（Windows 习惯如此）。

遮罩用 4 倍超采样渲染再缩小 → 边缘抗锯齿干净。
"""

from __future__ import annotations

import os
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    from xyxbot.console import enable_utf8

    enable_utf8()
except Exception:
    pass

from PIL import Image, ImageDraw, ImageFilter

ICO_DIR = ROOT / "packaging" / "icons"
SOURCE = ICO_DIR / "source-icon.png"

# ---- 可调参数 ----------------------------------------------------------
KEEP_WATERMARK = os.getenv("XYX_KEEP_WATERMARK", "") not in ("", "0")
WATERMARK_BOX = (1570, 1866, 1994, 1994)   # 实测出来的水印框
WATERMARK_SHIFT = 470                      # 从左侧多少像素处取背景来补
WATERMARK_FEATHER = 6                      # 边界羽化像素

MAC_CANVAS = 1024                          # macOS 画布
MAC_BODY = 880                             # 圆角方形本体边长（居中）
SQUIRCLE_N = 5.0                           # 超椭圆指数（Apple 约 5）
SS = 4                                     # 遮罩超采样倍数

WIN_SIZES = [16, 24, 32, 48, 64, 128, 256]

# ICNS 里的 PNG 块：类型码 → 该块的像素边长
#   icp4/icp5 = 16/32；ic11/ic12 = 32/64（@2x）；ic07/ic08/ic09/ic10 = 128/256/512/1024
#   ic13/ic14 = 128@2x / 256@2x（与 ic08/ic09 同尺寸，Apple 两套都要）
ICNS_CHUNKS = [
    ("icp4", 16), ("icp5", 32), ("ic11", 32), ("ic12", 64),
    ("ic07", 128), ("ic13", 256), ("ic08", 256),
    ("ic14", 512), ("ic09", 512), ("ic10", 1024),
]


# ---- 去水印 ------------------------------------------------------------
def remove_watermark(im: Image.Image) -> Image.Image:
    """用同一行左侧的**真实背景**盖掉水印（保留渐变与噪点）。"""
    im = im.copy()
    x0, y0, x1, y1 = WATERMARK_BOX
    w, h = im.size
    x0 = max(0, x0 - WATERMARK_FEATHER)
    y0 = max(0, y0 - WATERMARK_FEATHER)
    x1 = min(w, x1 + WATERMARK_FEATHER)
    y1 = min(h, y1 + WATERMARK_FEATHER)
    bw, bh = x1 - x0, y1 - y0

    # 从左侧 shift 处取同样大小的一块（那里是纯背景）
    sx = max(0, x0 - WATERMARK_SHIFT)
    patch = im.crop((sx, y0, sx + bw, y0 + bh))

    # 做一个羽化遮罩：中间不透明，四边渐隐，避免出现硬边
    mask = Image.new("L", (bw, bh), 255)
    d = ImageDraw.Draw(mask)
    f = WATERMARK_FEATHER
    for i in range(f):
        v = int(255 * i / f)
        d.rectangle([i, i, bw - 1 - i, bh - 1 - i], outline=v)
    mask = mask.filter(ImageFilter.GaussianBlur(f / 2))

    im.paste(patch, (x0, y0), mask)
    return im


# ---- 圆角外形（超椭圆）------------------------------------------------
def squircle_mask(size: int, n: float = SQUIRCLE_N, ss: int = SS) -> Image.Image:
    """生成一个抗锯齿的超椭圆遮罩（白=不透明）。"""
    big = size * ss
    m = Image.new("L", (big, big), 0)
    px = m.load()
    a = big / 2.0
    # 逐像素判定 |x/a|^n + |y/a|^n <= 1
    for y in range(big):
        dy = abs((y + 0.5) - a) / a
        dyn = dy ** n
        if dyn >= 1.0:
            continue
        # 解出 x 的边界，减少内层循环
        xmax = a * (1.0 - dyn) ** (1.0 / n)
        xs = int(a - xmax)
        xe = int(a + xmax)
        for x in range(max(0, xs), min(big, xe)):
            px[x, y] = 255
    return m.resize((size, size), Image.LANCZOS)


def macos_icon(master: Image.Image) -> Image.Image:
    """源图 → macOS 用的 1024 图标（圆角方形 + 透明边距）。"""
    body = master.resize((MAC_BODY, MAC_BODY), Image.LANCZOS).convert("RGBA")
    body.putalpha(squircle_mask(MAC_BODY))
    canvas = Image.new("RGBA", (MAC_CANVAS, MAC_CANVAS), (0, 0, 0, 0))
    off = (MAC_CANVAS - MAC_BODY) // 2
    canvas.paste(body, (off, off), body)
    return canvas


# ---- ICNS 容器 ---------------------------------------------------------
def write_icns(path: Path, images: dict) -> None:
    """按 Apple 的 ICNS 格式写文件。

    结构：
        'icns' <总长度 uint32be>
        然后若干块： <类型码 4 字节> <块长度 uint32be（含 8 字节头）> <PNG 数据>
    """
    import io

    body = b""
    for code, size in ICNS_CHUNKS:
        im = images[size]
        buf = io.BytesIO()
        im.save(buf, format="PNG", optimize=True)
        data = buf.getvalue()
        body += code.encode("ascii") + struct.pack(">I", len(data) + 8) + data
    path.write_bytes(b"icns" + struct.pack(">I", len(body) + 8) + body)


def read_icns(path: Path) -> list:
    """把 ICNS 读回来（用于自检）。返回 [(类型码, 声明长度, PNG宽, PNG高)]。"""
    raw = path.read_bytes()
    if raw[:4] != b"icns":
        raise ValueError("不是 ICNS 文件（缺 magic）")
    total = struct.unpack(">I", raw[4:8])[0]
    if total != len(raw):
        raise ValueError(f"声明的总长度 {total} 与实际 {len(raw)} 不符")
    out = []
    i = 8
    while i < len(raw):
        code = raw[i:i + 4].decode("ascii", "replace")
        ln = struct.unpack(">I", raw[i + 4:i + 8])[0]
        data = raw[i + 8:i + ln]
        w = h = -1
        if data[:8] == b"\x89PNG\r\n\x1a\n":
            w, h = struct.unpack(">II", data[16:24])
        out.append((code, ln, w, h))
        i += ln
    return out


# ---- 主流程 ------------------------------------------------------------
def main() -> int:
    if not SOURCE.exists():
        print(f"✗ 找不到源图：{SOURCE}")
        return 1

    src = Image.open(SOURCE).convert("RGB")
    print(f"源图      : {SOURCE.name}  {src.size[0]}x{src.size[1]}")

    if KEEP_WATERMARK:
        print("去水印    : 已跳过（XYX_KEEP_WATERMARK=1）")
        clean = src
    else:
        clean = remove_watermark(src)
        print(f"去水印    : 已处理 {WATERMARK_BOX}（从左侧 {WATERMARK_SHIFT}px 取背景）")

    clean_path = ICO_DIR / "icon-clean.png"
    clean.save(clean_path, optimize=True)
    print(f"           干净版已存 {clean_path.name}")

    # ---- macOS ----
    mac = macos_icon(clean)
    mac_1024 = ICO_DIR / "icon-1024.png"
    mac.save(mac_1024, optimize=True)

    sizes = {}
    for _code, n in ICNS_CHUNKS:
        if n not in sizes:
            sizes[n] = mac.resize((n, n), Image.LANCZOS)
    icns = ICO_DIR / "icon.icns"
    write_icns(icns, sizes)
    got = read_icns(icns)
    print(f"macOS     : icon.icns  {icns.stat().st_size/1024:.1f} KB  "
          f"{len(got)} 块")
    for code, ln, w, h in got:
        print(f"            {code}  {ln:>7d}B  {w}x{h}")

    # ---- Windows ----
    ico = ICO_DIR / "icon.ico"
    clean.convert("RGBA").save(ico, format="ICO", sizes=[(s, s) for s in WIN_SIZES])
    with Image.open(ico) as back:
        n_ico = len(getattr(back, "ico", None).sizes()) if hasattr(back, "ico") \
            else 0
    print(f"Windows   : icon.ico  {ico.stat().st_size/1024:.1f} KB  "
          f"{sorted(getattr(Image.open(ico), 'ico').sizes())}")

    # ---- 通用小图 ----
    small = ICO_DIR / "icon-256.png"
    mac.resize((256, 256), Image.LANCZOS).save(small, optimize=True)
    print(f"通用      : icon-256.png  {small.stat().st_size/1024:.1f} KB")

    print("\n✓ 图标生成完成")
    return 0


if __name__ == "__main__":
    sys.exit(main())

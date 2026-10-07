"""配色与绘制小工具（纯数据 + 两个纯函数，不依赖 Tk）。

本文件由原巨型模块拆分而来（Phase C2/C1），拆分时按 AST 依赖做了拓扑排序，
每个模块只 import 排在自己前面的模块，不存在循环引用。
"""

from __future__ import annotations

import tkinter as tk

__all__ = ["COLOR", "GRADIENT_BRAND", "LEVEL_COLOR", "_lerp_color", "round_rect"]

# ---------------------------------------------------------------- 配色

COLOR = {
    # 背景层次（由深到浅）
    "bg_root": "#0d1117",        # 最底层
    "bg_card": "#161b22",        # 卡片
    "bg_card_hi": "#1c2128",     # 卡片悬浮
    "bg_input": "#21262d",       # 输入框
    "bg_titlebar": "#010409",    # 标题栏

    # 品牌色（金色系，配「赵氏集团」的尊贵感）
    "brand": "#d4a24c",
    "brand_hi": "#e8bb6b",
    "brand_dim": "#8a6a2f",

    # 语义色
    "accent": "#58a6ff",         # 信息蓝
    "success": "#3fb950",        # 成功绿
    "warning": "#d29922",        # 警告黄
    "danger": "#f85149",         # 危险红

    # 文字
    "text": "#e6edf3",           # 主文字
    "text_dim": "#8b949e",       # 次要文字
    "text_mute": "#6e7681",      # 弱化文字
    "text_on_brand": "#1a1206",  # 品牌色上的文字

    # 描边
    "border": "#30363d",
    "border_hi": "#484f58",
}


# 渐变用的品牌色序列（标题栏左→右）
GRADIENT_BRAND = ["#1a1206", "#2b1f0a", "#3d2a0d", "#2b1f0a", "#1a1206"]


# 日志级别颜色
LEVEL_COLOR = {
    "info": COLOR["text_dim"],
    "ok": COLOR["success"],
    "warn": COLOR["warning"],
    "err": COLOR["danger"],
    "brand": COLOR["brand"],
}



# ---------------------------------------------------------------- 工具

def _lerp_color(c1: str, c2: str, t: float) -> str:
    """两色线性插值，用于渐变。"""
    def h2r(c):
        c = c.lstrip("#")
        return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)

    r1, g1, b1 = h2r(c1)
    r2, g2, b2 = h2r(c2)
    r = int(r1 + (r2 - r1) * t)
    g = int(g1 + (g2 - g1) * t)
    b = int(b1 + (b2 - b1) * t)
    return f"#{r:02x}{g:02x}{b:02x}"



def round_rect(canvas: tk.Canvas, x1, y1, x2, y2, r: int = 12, **kw):
    """在 Canvas 上画圆角矩形（用多边形近似）。"""
    pts = [
        x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r,
        x2, y2 - r, x2, y2, x2 - r, y2,
        x1 + r, y2, x1, y2, x1, y2 - r,
        x1, y1 + r, x1, y1,
    ]
    return canvas.create_polygon(pts, smooth=True, **kw)

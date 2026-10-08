"""按钮与勾选、进度条类。

本文件由原巨型模块拆分而来（Phase C2/C1），拆分时按 AST 依赖做了拓扑排序，
每个模块只 import 排在自己前面的模块，不存在循环引用。
"""

from __future__ import annotations

from typing import Callable, Optional
from xyxbot.ui.theme.fonts import F, FM
from xyxbot.ui.theme.palette import COLOR, GRADIENT_BRAND, LEVEL_COLOR, _lerp_color, round_rect
from xyxbot.ui.theme.redraw import bind_configure
import tkinter as tk

__all__ = ["BrandButton", "CheckBox", "GradientBar"]



class GradientBar(tk.Canvas):
    """渐变标题栏。"""

    def __init__(self, master, height: int = 64, colors=None, **kw):
        super().__init__(
            master, height=height, bg=COLOR["bg_titlebar"],
            highlightthickness=0, bd=0, **kw
        )
        self._colors = colors or GRADIENT_BRAND
        bind_configure(self, self._draw)      # 守卫版（防 macOS Configure 死循环）

    def _draw(self, event=None):
        self.delete("grad")
        w = self.winfo_width()
        h = self.winfo_height()
        if w < 2:
            return
        n = len(self._colors) - 1
        step = max(1, w // 120)
        for x in range(0, w, step):
            t = x / max(1, w)
            idx = min(int(t * n), n - 1)
            local_t = (t * n) - idx
            col = _lerp_color(self._colors[idx], self._colors[idx + 1], local_t)
            self.create_rectangle(x, 0, x + step, h, fill=col, outline="", tags="grad")
        self.tag_lower("grad")




class BrandButton(tk.Canvas):
    """品牌色圆角按钮，带 hover / press / disabled 状态。"""

    def __init__(self, master, text: str, command: Optional[Callable] = None,
                 width: int = 160, height: int = 38, radius: int = 8,
                 style: str = "primary", font_size: int = 10, **kw):
        bg = kw.pop("bg", COLOR["bg_card"])
        super().__init__(master, width=width, height=height, bg=bg,
                         highlightthickness=0, bd=0, **kw)
        self._text = text
        self._cmd = command
        self._btn_w = width
        self._btn_h = height
        self._r = radius
        self._style = style
        self._enabled = True
        self._state = "normal"  # normal | hover | press | disabled

        self._font = F(font_size, True)
        # 首次绘制用构造尺寸；组件真正布局后再按实际尺寸重绘
        self._render(width, height)
        bind_configure(self, self._render_from_cfg)   # 守卫版（防死循环）

        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<ButtonPress-1>", self._on_press)
        self.bind("<ButtonRelease-1>", self._on_release)

    # ---- 配色
    def _colors(self):
        if not self._enabled:
            return COLOR["bg_input"], COLOR["text_mute"], COLOR["border"]
        if self._style == "primary":
            base = COLOR["brand"]
            if self._state == "hover":
                base = COLOR["brand_hi"]
            elif self._state == "press":
                base = COLOR["brand_dim"]
            return base, COLOR["text_on_brand"], base
        if self._style == "ghost":
            base = COLOR["bg_card_hi"]
            if self._state == "hover":
                base = "#262c36"
            elif self._state == "press":
                base = COLOR["bg_input"]
            return base, COLOR["text"], COLOR["border_hi"]
        if self._style == "danger":
            base = COLOR["danger"]
            if self._state == "hover":
                base = "#ff6b63"
            elif self._state == "press":
                base = "#c9413a"
            return base, "#ffffff", base
        return COLOR["bg_input"], COLOR["text"], COLOR["border"]

    def _render_from_cfg(self):
        """由 `bind_configure` 调用（零参数）：用守卫记下的尺寸重绘。

        ★ 尺寸是否变化由 `bind_configure` 判断 —— 尺寸没变它压根不会调这里。
        """
        self._btn_w, self._btn_h = self._cfg_w, self._cfg_h
        self._render(self._btn_w, self._btn_h)

    def _render(self, w: int = None, h: int = None):
        w = w or self._btn_w
        h = h or self._btn_h
        if w < 4 or h < 4:
            return
        self._btn_w, self._btn_h = w, h
        self.delete("all")
        fill, fg, outline = self._colors()
        round_rect(self, 1, 1, w - 1, h - 1, self._r,
                   fill=fill, outline=outline, width=1)
        self.create_text(w / 2, h / 2, text=self._text,
                         font=self._font, fill=fg)

    # ---- 事件
    def _on_enter(self, _):
        if self._enabled:
            self._state = "hover"
            self._render()
            self.configure(cursor="hand2")

    def _on_leave(self, _):
        self._state = "normal"
        self._render()

    def _on_press(self, _):
        if self._enabled:
            self._state = "press"
            self._render()

    def _on_release(self, event):
        if not self._enabled:
            return
        self._state = "hover"
        self._render()
        if 0 <= event.x <= self._btn_w and 0 <= event.y <= self._btn_h and self._cmd:
            self._cmd()

    # ---- 公开
    def set_enabled(self, on: bool):
        self._enabled = on
        self._state = "normal" if on else "disabled"
        self._render()

    def config(self, cnf=None, **kw):
        """★ 让 `config(state="disabled")` 真正生效。

        背景（实测 bug）：本组件继承 tk.Canvas，而 Canvas 虽然**接受** state
        选项，但外层 widget state **不会拦截** `<Button-1>` 绑定 ——
        事件照旧触发 `_on_release`，而它只看 `self._enabled`。
        于是 `btn.config(state="disabled")` 视觉上变灰、实际仍可点击，
        忙碌期间会重复触发任务。

        这里把 `state` 参数转成 `set_enabled()`，其余选项原样交给 tk 的 config。
        """
        state = None
        if cnf and isinstance(cnf, dict) and "state" in cnf:
            state = cnf.pop("state")
        if "state" in kw:
            state = kw.pop("state")
        if state is not None:
            self.set_enabled(state not in ("disabled", "disable", False))
        # 转发给 tk.Canvas（可能还剩别的选项，也可能为空）
        if cnf or kw:
            return super().config(cnf, **kw)
        return None

    def configure(self, cnf=None, **kw):
        """tk 的 configure 是 config 的别名，保持一致行为。"""
        return self.config(cnf, **kw)

    def set_text(self, text: str):
        self._text = text
        self._render()




class CheckBox(tk.Canvas):
    """深色主题复选框：方块 + 文字，可点击整行切换。"""

    def __init__(self, master, text: str = "", checked: bool = False,
                 command: Optional[Callable] = None, width: int = 200,
                 height: int = 22, **kw):
        bg = kw.pop("bg", COLOR["bg_root"])
        super().__init__(master, width=width, height=height, bg=bg,
                         highlightthickness=0, bd=0, **kw)
        self._text = text
        self._checked = bool(checked)
        self._cmd = command
        self._hover = False
        self._cw, self._ch = width, height

        bind_configure(self, self._render_from_cfg)   # 守卫版（防死循环）
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<Button-1>", self._on_click)
        self._render()

    def _render_from_cfg(self):
        """由 `bind_configure` 调用（零参数）：用守卫记下的尺寸重绘。"""
        self._cw, self._ch = self._cfg_w, self._cfg_h
        self._render()

    def _on_enter(self, _):
        self._hover = True
        self.configure(cursor="hand2")
        self._render()

    def _on_leave(self, _):
        self._hover = False
        self._render()

    def _on_click(self, _):
        self._checked = not self._checked
        self._render()
        if self._cmd:
            self._cmd(self._checked)

    def _render(self):
        self.delete("all")
        h = self._ch
        box = 16
        y0 = (h - box) // 2

        # 方块
        if self._checked:
            round_rect(self, 1, y0, 1 + box, y0 + box, 4,
                       fill=COLOR["brand"], outline=COLOR["brand"])
            # 勾
            self.create_line(5, y0 + 8, 8, y0 + 11, 13, y0 + 5,
                             fill=COLOR["text_on_brand"], width=2,
                             capstyle="round", joinstyle="round")
        else:
            border = COLOR["brand"] if self._hover else COLOR["border_hi"]
            round_rect(self, 1, y0, 1 + box, y0 + box, 4,
                       fill=COLOR["bg_input"], outline=border)

        # 文字
        col = COLOR["text"] if (self._hover or self._checked) else COLOR["text_dim"]
        self.create_text(box + 10, h / 2, anchor="w", text=self._text,
                         font=F(9), fill=col)

    # ---- 对外
    def get(self) -> bool:
        return self._checked

    def set(self, on: bool):
        self._checked = bool(on)
        self._render()

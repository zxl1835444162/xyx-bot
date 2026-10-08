"""侧栏导航项控件。

由 `xyxbot/ui/main_window.py` 拆分而来（class split）。
"""

from __future__ import annotations

from xyxbot.ui.theme import (COLOR, F, BrandButton, CheckBox, GradientBar, LogView,
                    StatusBar, bind_configure, bind_wheel, bind_wheel_all,
                    round_rect, unbind_wheel_all, wheel_units)
import tkinter as tk



# ================================================================ 组件

class NavItem(tk.Canvas):
    """侧边导航项，带选中态与 hover。"""

    def __init__(self, master, icon: str, text: str, command=None,
                 width: int = 176, height: int = 42, **kw):
        bg = kw.pop("bg", COLOR["bg_root"])
        super().__init__(master, width=width, height=height, bg=bg,
                         highlightthickness=0, bd=0, **kw)
        self._icon = icon
        self._text = text
        self._cmd = command
        self._active = False
        self._hover = False
        self._nw, self._nh = width, height

        bind_configure(self, self._render_from_cfg)   # 守卫版（防 Configure 死循环）
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<Button-1>", lambda e: self._cmd and self._cmd())
        self._render()

    def _render_from_cfg(self):
        """由 `bind_configure` 调用（零参数）：用守卫记下的尺寸重绘。"""
        self._nw, self._nh = self._cfg_w, self._cfg_h
        self._render()

    def _on_enter(self, _):
        self._hover = True
        self.configure(cursor="hand2")
        self._render()

    def _on_leave(self, _):
        self._hover = False
        self._render()

    def set_active(self, on: bool):
        self._active = on
        self._render()

    def _render(self):
        self.delete("all")
        w, h = self._nw, self._nh
        if w < 4:
            return

        if self._active:
            round_rect(self, 1, 1, w - 1, h - 1, 8,
                       fill=COLOR["bg_card"], outline=COLOR["brand"], width=1)
            # 左侧强调条
            round_rect(self, 1, 9, 4, h - 9, 2,
                       fill=COLOR["brand"], outline="")
            fg = COLOR["brand"]
            tcol = COLOR["text"]
        elif self._hover:
            round_rect(self, 1, 1, w - 1, h - 1, 8,
                       fill=COLOR["bg_card_hi"], outline="")
            fg, tcol = COLOR["text_dim"], COLOR["text"]
        else:
            fg, tcol = COLOR["text_mute"], COLOR["text_dim"]

        self.create_text(24, h / 2, text=self._icon, font=F(11), fill=fg)
        self.create_text(46, h / 2, anchor="w", text=self._text,
                         font=F(10, self._active), fill=tcol)

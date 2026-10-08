"""小控件：标题 / 暗字 / 状态条 / 浮层提示。

本文件由原巨型模块拆分而来（Phase C2/C1），拆分时按 AST 依赖做了拓扑排序，
每个模块只 import 排在自己前面的模块，不存在循环引用。
"""

from __future__ import annotations

from xyxbot.ui.theme.fonts import F, FM
from xyxbot.ui.theme.palette import COLOR, GRADIENT_BRAND, LEVEL_COLOR, _lerp_color, round_rect
from xyxbot.ui.theme.redraw import bind_configure
import tkinter as tk

__all__ = ["DimLabel", "StatusBar", "TitleLabel", "Toast"]



class TitleLabel(tk.Label):
    def __init__(self, master, text: str, size: int = 12, color=None, **kw):
        super().__init__(
            master, text=text, font=F(size, True),
            bg=kw.pop("bg", COLOR["bg_card"]),
            fg=color or COLOR["text"], **kw,
        )




class DimLabel(tk.Label):
    def __init__(self, master, text: str, size: int = 9, **kw):
        super().__init__(
            master, text=text, font=F(size),
            bg=kw.pop("bg", COLOR["bg_card"]),
            fg=kw.pop("fg", COLOR["text_dim"]), **kw,
        )




class StatusBar(tk.Canvas):
    """底部状态栏：左侧状态点 + 文字，右侧版本号。"""

    def __init__(self, master, height: int = 30, version: str = "", **kw):
        super().__init__(master, height=height, bg=COLOR["bg_titlebar"],
                         highlightthickness=0, bd=0, **kw)
        self._status = "就绪"
        self._level = "info"
        self._version = version
        bind_configure(self, self._draw)      # 守卫版（防 macOS Configure 死循环）

    def set_status(self, text: str, level: str = "info"):
        self._status = text
        self._level = level
        self._draw()

    def _draw(self, event=None):
        self.delete("all")
        w = self.winfo_width()
        h = self.winfo_height()
        if w < 2:
            return

        col = LEVEL_COLOR.get(self._level, COLOR["text_dim"])
        self.create_oval(14, h / 2 - 4, 22, h / 2 + 4, fill=col, outline="")
        self.create_text(30, h / 2, anchor="w", text=self._status,
                         font=F(9), fill=COLOR["text_dim"])
        if self._version:
            self.create_text(w - 14, h / 2, anchor="e", text=self._version,
                             font=F(8), fill=COLOR["text_mute"])




class Toast(tk.Frame):
    """轻量提示条：贴在父容器底部，几秒后自动消失。"""

    def __init__(self, master, text: str, level: str = "info",
                 duration: int = 2600, **kw):
        bg = kw.pop("bg", COLOR["bg_card_hi"])
        super().__init__(master, bg=bg, **kw)
        self._master = master

        col = LEVEL_COLOR.get(level, COLOR["text_dim"])
        bar = tk.Frame(self, bg=col, width=3)
        bar.pack(side="left", fill="y")

        tk.Label(self, text=text, font=F(9), bg=bg, fg=COLOR["text"],
                 padx=12, pady=8).pack(side="left")

        self.place(relx=0.5, rely=1.0, anchor="s", y=-16)
        self.after(duration, self._dismiss)

    def _dismiss(self):
        try:
            self.destroy()
        except Exception:
            pass

"""输入框。

本文件由原巨型模块拆分而来（Phase C2/C1），拆分时按 AST 依赖做了拓扑排序，
每个模块只 import 排在自己前面的模块，不存在循环引用。
"""

from __future__ import annotations

from xyxbot.ui.theme.fonts import F, FM
from xyxbot.ui.theme.palette import COLOR, GRADIENT_BRAND, LEVEL_COLOR, _lerp_color, round_rect
from xyxbot.ui.theme.redraw import bind_configure
import tkinter as tk

__all__ = ["DarkEntry"]



class DarkEntry(tk.Frame):
    """深色输入框，带占位符与聚焦高亮。

    实现要点：
        - Canvas 只负责画背景（圆角 + 图标 + 边框高亮）
        - 真正的 tk.Entry 用 place 叠在 Canvas 之上（不放进 Canvas 内部），
          这样鼠标点击能正常落到输入框上
        - ★ 占位符不能画在 Canvas 上 —— Entry 是不透明方块，会把它盖住。
          正确做法是把 placeholder 写进 Entry 自身，用前景色区分「是占位符」，
          并在获得焦点/输入内容时清除。
    """

    def __init__(self, master, placeholder: str = "", width: int = 30,
                 show: str = "", icon: str = "", height: int = 40, **kw):
        bg = kw.pop("bg", COLOR["bg_card"])
        super().__init__(master, bg=bg, height=height, width=width, **kw)
        self.pack_propagate(False)

        self._placeholder = placeholder
        self._show = show
        self._icon = icon
        self._focused = False
        self._is_placeholder = False      # 当前 Entry 里显示的是占位符吗
        self._init_w = width
        self._init_h = height

        # 背景层
        self._canvas = tk.Canvas(self, bg=bg, highlightthickness=0, bd=0)
        self._canvas.place(x=0, y=0, relwidth=1, relheight=1)

        # 输入层：直接放在 Frame 上，叠在 Canvas 之上
        self._var = tk.StringVar()
        self.entry = tk.Entry(
            self, textvariable=self._var, font=F(10),
            bg=COLOR["bg_input"], fg=COLOR["text"],
            insertbackground=COLOR["brand"],
            relief="flat", bd=0, highlightthickness=0,
            show="",                       # 先不设，占位符阶段不能掩码
        )
        self.entry.place(x=40, y=(height - 22) // 2, width=width - 56, height=22)

        self.entry.bind("<FocusIn>", self._on_focus_in)
        self.entry.bind("<FocusOut>", self._on_focus_out)
        self.entry.bind("<Key>", self._on_key)
        # 点 Frame 内任何位置都聚焦到输入框（Canvas / 图标区 / 空白区）
        self._canvas.bind("<Button-1>", self._click_focus)
        self.bind("<Button-1>", self._click_focus)
        # ★ DarkEntry 的 Configure 里会 place_configure 输入框 ——
        #   这正是最容易造成 "Configure→改子控件→再 Configure" 死循环的写法，
        #   必须用守卫版。
        bind_configure(self, self._on_frame_config_guarded)

        # 初始填占位符 + 画背景
        self._show_placeholder()
        self.after(20, self._redraw)

    # ---- 占位符

    def _show_placeholder(self):
        if not self._placeholder:
            return
        self._is_placeholder = True
        self.entry.configure(fg=COLOR["text_mute"], show="")
        self._var.set(self._placeholder)

    def _clear_placeholder(self):
        if not self._is_placeholder:
            return False
        self._is_placeholder = False
        self._var.set("")
        self.entry.configure(fg=COLOR["text"], show=self._show)
        return True

    def _on_key(self, event):
        """用户一开始打字，就把占位符清掉。"""
        if self._is_placeholder and event.keysym not in (
                "Left", "Right", "Up", "Down", "Home", "End", "Tab",
                "Shift_L", "Shift_R", "Control_L", "Control_R",
                "Alt_L", "Alt_R", "Caps_Lock"):
            self._clear_placeholder()

    # ---- 事件

    def _click_focus(self, event):
        """点 Canvas 空白区域也能聚焦到输入框。"""
        self.entry.focus_set()

    def _on_frame_config_guarded(self):
        """由 `bind_configure` 调用（零参数）：尺寸从 `_cfg_w/_cfg_h` 取。

        ★ 这里既重绘、又 `place_configure` 输入框 —— 正是最容易造成
          "Configure → 改动子控件 → 再 Configure" 死循环的写法。
          尺寸没变时 `bind_configure` 根本不会调到这里，循环就断了。
        """
        w, h = self._cfg_w, self._cfg_h
        self._redraw(w, h)
        # 输入框跟随 Frame 尺寸
        self.entry.place_configure(
            x=40, width=max(10, w - 56),
            y=max(0, (h - 22) // 2),
        )

    def _on_focus_in(self, _):
        self._focused = True
        self._redraw()

    def _on_focus_out(self, _):
        self._focused = False
        # 失焦且内容为空 → 恢复占位符
        if not self._var.get().strip() and not self._is_placeholder:
            self._show_placeholder()
        self._redraw()

    # ---- 绘制

    def _redraw(self, w: int = None, h: int = None):
        c = self._canvas
        w = w or self.winfo_width() or self._init_w
        h = h or self.winfo_height() or self._init_h
        if w < 4:
            return
        c.delete("all")

        border = COLOR["brand"] if self._focused else COLOR["border"]
        round_rect(c, 1, 1, w - 2, h - 2, 8,
                   fill=COLOR["bg_input"], outline=border, width=1)

        # 图标
        if self._icon:
            c.create_text(20, h / 2, text=self._icon, font=F(11),
                          fill=COLOR["brand"] if self._focused else COLOR["text_mute"])

    # ---- 对外

    def get(self) -> str:
        """取真实内容（占位符状态返回空串）。"""
        if self._is_placeholder:
            return ""
        return self._var.get()

    def set(self, v: str):
        """设置内容（会清掉占位符）。"""
        self._is_placeholder = False
        self.entry.configure(fg=COLOR["text"], show=self._show)
        self._var.set(v or "")

    def focus(self):
        self.entry.focus_set()

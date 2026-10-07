"""控件类（Card / BrandButton / DarkEntry / LogView …）。

本文件由原巨型模块拆分而来（Phase C2/C1），拆分时按 AST 依赖做了拓扑排序，
每个模块只 import 排在自己前面的模块，不存在循环引用。
"""

from __future__ import annotations

from typing import Callable, Optional
import tkinter as tk

from xyxbot.ui.theme.fonts import F, FM
from xyxbot.ui.theme.palette import COLOR, GRADIENT_BRAND, LEVEL_COLOR, _lerp_color, round_rect
from xyxbot.ui.theme.redraw import bind_configure

__all__ = ["BrandButton", "Card", "CheckBox", "Collapsible", "DarkEntry", "DimLabel", "GradientBar", "LogView", "StatusBar", "TitleLabel", "Toast"]


# ---------------------------------------------------------------- 组件

class Card(tk.Frame):
    """圆角卡片容器。内部用 self.body 放内容。"""

    def __init__(self, master, title: str = "", pad: int = 14, radius: int = 12, **kw):
        super().__init__(master, bg=COLOR["bg_root"], **kw)
        self.radius = radius
        self._title = title
        self._pad = pad

        self._canvas = tk.Canvas(
            self, bg=COLOR["bg_root"], highlightthickness=0, bd=0
        )
        self._canvas.pack(fill="both", expand=True)

        # 内容容器（透明地叠在 Canvas 上）
        self.body = tk.Frame(self._canvas, bg=COLOR["bg_card"])
        self._win = self._canvas.create_window(
            pad, pad, anchor="nw", window=self.body
        )

        # ★ 用带守卫的绑定（原来直接 bind → macOS 上 Configure 死循环）
        bind_configure(self, self._redraw)
        # ★★ Card.body 也走守卫版（2026-10-04）：
        #   之前这里是**裸绑** `self.body.bind("<Configure>", …)`，被
        #   `tests/test_configure_guard.py` 以「内部已有 != 判断」为由放行 ——
        #   但那个理由只对 canvas 那行成立，`self.configure(height=need)`
        #   并没有 `!=` 判断。macOS 上 Configure 每次重绘都会再发一次，
        #   于是 body → _resize_win → self.configure(height) → self 的
        #   Configure → _redraw → _resize_win → … 形成渲染风暴，
        #   主线程回不到事件循环（用户看到的「界面出不来 + 鼠标转圈」）。
        #   走 bind_configure 后：尺寸没变就不重绘 + 全局每秒上限兜底。
        bind_configure(self.body, self._resize_win)
        # 初次布局兜底
        self.after(40, self._redraw)
        self.after(40, self._resize_win)

    def _resize_win(self):
        """★ 让卡片高度跟随 body 的实际内容高度。

        ★ 为什么必须这么干（2026-10-03 踩坑）：
          Card = Frame + Canvas，Canvas **不会因为内部 window 变高而报告
          reqheight**。结果是卡片高度只按「外部给的空间」算，body 里超过
          这个高度的内容会被**直接裁掉**（AI 续写卡加到 6 行后就露馅了：
          底部「生成字数（自动采纳）」「一键续写」按钮完全看不见）。
          所以这里把 Canvas 的高度显式设成 body 的 reqheight + 上下留白。

        ★★ 每一处 configure 都必须有 `!= 判断`（2026-10-04，macOS 风暴）
           `configure(height=…)` 一旦真的改变了尺寸，就会再发一个
           `<Configure>`。macOS 的 Tk 对这种变化特别敏感，不做「值没变就
           不写」的判断就会自激。这里两个 height 都加了 !=，彻底断掉回路。
        """
        c = self._canvas
        try:
            top = self._pad + (18 if self._title else 0)
            need = self.body.winfo_reqheight() + top + self._pad
            if need > 4 and c.winfo_reqheight() != need:
                c.configure(height=need)     # ← 关键：把内容高度告诉布局器
            if c.cget("scrollregion") != str(c.bbox("all")):
                c.configure(scrollregion=c.bbox("all"))
            # 卡片本身也报这个高度，父容器才会给它空间
            # ★ 必须判断「值真的变了」才写，否则每次 Configure 都写一次 → 自激
            if need > 4 and self.winfo_reqheight() != need:
                self.configure(height=need)
        except Exception:
            pass

    def _redraw(self, event=None):
        c = self._canvas
        c.delete("bgshape")
        w = self.winfo_width()
        h = self.winfo_height()
        if w < 4 or h < 4:
            return
        round_rect(
            c, 1, 1, w - 2, h - 2, self.radius,
            fill=COLOR["bg_card"], outline=COLOR["border"], width=1, tags="bgshape",
        )
        c.tag_lower("bgshape")
        # 内容宽度自适应
        self._canvas.coords(self._win, self._pad, self._pad + (18 if self._title else 0))
        self._canvas.itemconfigure(
            self._win, width=max(1, w - self._pad * 2)
        )
        # ★ 顺带把高度也校准一次（内容可能刚变）
        self._resize_win()



class TitleLabel(tk.Label):
    def __init__(self, master, text: str, size: int = 12, color=None, **kw):
        super().__init__(
            master, text=text, font=F(size, True),
            bg=kw.pop("bg", COLOR["bg_card"]),
            fg=color or COLOR["text"], **kw,
        )



class Collapsible(tk.Frame):
    """★ 可折叠卡片（2026-10-04 UI 精简用）。

    只显示一个标题栏，点一下展开/收起 body。
    用 pack/pack_forget 实现，简单可靠，不依赖 Canvas 高度计算。

    用法::
        col = Collapsible(parent, title="指令模板", default_open=False)
        col.body   # 往这里 pack 你的内容
        col.pack(fill="x")
    """

    def __init__(self, master, title: str = "", default_open: bool = False,
                 bg: str = None, **kw):
        bg = bg or COLOR["bg_card"]
        super().__init__(master, bg=COLOR["bg_root"], **kw)

        self._open = bool(default_open)

        # 标题栏（可点击）
        self._bar = tk.Frame(self, bg=bg, cursor="hand2",
                             highlightbackground=COLOR["border"],
                             highlightthickness=1)
        self._bar.pack(fill="x")

        self._arrow = tk.Label(self._bar, text="▸", font=F(11, True),
                               bg=bg, fg=COLOR["brand"], width=2)
        self._arrow.pack(side="left", padx=(8, 0), pady=6)

        self._title = tk.Label(self._bar, text=title, font=F(10, True),
                               bg=bg, fg=COLOR["text"])
        self._title.pack(side="left", pady=7)

        # body（初始按 default_open 决定是否显示）
        self.body = tk.Frame(self, bg=COLOR["bg_card"],
                             highlightbackground=COLOR["border"],
                             highlightthickness=1)
        # body 用 pack 控制显隐，收起时不占空间
        self._body_packed = False
        if self._open:
            self.body.pack(fill="x")
            self._body_packed = True
            self._arrow.config(text="▾")

        # 点击标题栏切换
        for w in (self._bar, self._arrow, self._title):
            w.bind("<Button-1>", self._toggle)

    def _toggle(self, event=None):
        self._open = not self._open
        if self._open:
            self.body.pack(fill="x")
            self._body_packed = True
            self._arrow.config(text="▾")
        else:
            self.body.pack_forget()
            self._body_packed = False
            self._arrow.config(text="▸")

    def set_open(self, open_: bool):
        if bool(open_) != self._open:
            self._toggle()

    @property
    def is_open(self) -> bool:
        return self._open



class DimLabel(tk.Label):
    def __init__(self, master, text: str, size: int = 9, **kw):
        super().__init__(
            master, text=text, font=F(size),
            bg=kw.pop("bg", COLOR["bg_card"]),
            fg=kw.pop("fg", COLOR["text_dim"]), **kw,
        )



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



class LogView(tk.Frame):
    """带等级着色的日志区，支持「只看关键节点」。

    ★★ 为什么要有过滤（2026-10-04 界面重设计）
        跑 100 章会产生几百行日志，其中大部分是"切换页面""预检 ✓"这类
        过程噪音，真正要看的只有**每章的结果**（✓/✗/⚠/中止）。
        所以给每条日志打两个标签：等级标签（管颜色）+ `noise` 标签
        （管是否被过滤掉）。过滤通过 Tk 的 `elide` 实现 —— **只是不显示，
        内容还在**，关掉过滤立刻全回来，不需要重放日志。

    等级约定：
        info / dim  → 过程噪音（切页、展开、提示）
        ok / warn / err / brand → 关键节点（结果、错误、阶段标题）
    """

    #: 会被「只看关键节点」隐藏的等级
    NOISE_LEVELS = ("info", "dim")
    NOISE_TAG = "noise"

    def __init__(self, master, height: int = 12, **kw):
        bg = kw.pop("bg", COLOR["bg_card"])
        super().__init__(master, bg=bg, **kw)

        self.text = tk.Text(
            self, height=height, wrap="word", font=FM(9),
            bg="#0b0f14", fg=COLOR["text_dim"],
            insertbackground=COLOR["brand"],
            relief="flat", bd=0, highlightthickness=0,
            padx=12, pady=10, state="disabled",
            selectbackground=COLOR["brand_dim"],
        )
        sb = tk.Scrollbar(self, command=self.text.yview,
                         bg=COLOR["bg_input"], troughcolor=COLOR["bg_root"],
                         relief="flat", bd=0, width=8,
                         activebackground=COLOR["border_hi"])
        self.text.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.text.pack(side="left", fill="both", expand=True)

        for lvl, col in LEVEL_COLOR.items():
            self.text.tag_configure(lvl, foreground=col)
        # ★ 噪音标签必须**最后**配置：Tk 里后建的标签优先级更高，
        #   而它只设 elide、不设 foreground，所以颜色仍由等级标签决定。
        self.text.tag_configure(self.NOISE_TAG, elide=False)
        self._key_only = False

    def log(self, msg: str, level: str = "info"):
        """线程安全地追加一行日志。"""
        try:
            self.text.configure(state="normal")
            tags = (level, self.NOISE_TAG) if level in self.NOISE_LEVELS \
                else (level,)
            self.text.insert("end", msg + "\n", tags)
            self.text.see("end")
            self.text.configure(state="disabled")
        except Exception:
            pass

    def clear(self):
        try:
            self.text.configure(state="normal")
            self.text.delete("1.0", "end")
            self.text.configure(state="disabled")
        except Exception:
            pass

    # ------------------------------------------------ ★ 只看关键节点

    def set_key_only(self, on: bool):
        """开/关「只看关键节点」。

        实现是给噪音行所在的 `noise` 标签设 `elide` —— Tk 会把这些行
        **从显示里折叠掉**，但内容仍在 Text 里；关掉就立刻全回来。
        所以这个开关是**无损**的，不会丢日志。
        """
        self._key_only = bool(on)
        try:
            self.text.tag_configure(self.NOISE_TAG, elide=bool(on))
        except Exception:
            pass
        try:
            self.text.see("end")
        except Exception:
            pass

    def key_only(self) -> bool:
        return bool(getattr(self, "_key_only", False))

    def toggle_key_only(self) -> bool:
        self.set_key_only(not self.key_only())
        return self.key_only()



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

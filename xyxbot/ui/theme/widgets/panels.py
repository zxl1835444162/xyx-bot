"""容器类控件：卡片 / 折叠区 / 日志视图。

本文件由原巨型模块拆分而来（Phase C2/C1），拆分时按 AST 依赖做了拓扑排序，
每个模块只 import 排在自己前面的模块，不存在循环引用。
"""

from __future__ import annotations

from xyxbot.ui.theme.fonts import F, FM
from xyxbot.ui.theme.palette import COLOR, GRADIENT_BRAND, LEVEL_COLOR, _lerp_color, round_rect
from xyxbot.ui.theme.redraw import bind_configure
import tkinter as tk

__all__ = ["Card", "Collapsible", "LogView"]


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

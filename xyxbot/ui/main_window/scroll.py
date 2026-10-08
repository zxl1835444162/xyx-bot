"""卡片式滚动区（内容宽度跟随、滚轮绑定）。

由 `xyxbot/ui/main_window.py` 拆分而来（class split）：只搬位置、
不改逻辑（方法体、注释、装饰器、超时值全部原样）。
"""

from __future__ import annotations

from xyxbot.ui.theme import (COLOR, F, BrandButton, CheckBox, GradientBar, LogView,
                    StatusBar, bind_configure, bind_wheel, bind_wheel_all,
                    round_rect, unbind_wheel_all, wheel_units)
import tkinter as tk


class ScrollMixin:
    """卡片式滚动区（内容宽度跟随、滚轮绑定）。"""

    def _build_scroll_area(self, parent):
        """把内容区做成可整页滚动的容器。

        ★ 为什么：内容页（小说分章）卡片很多，小屏幕/高 DPI 下会超出可视高度，
          底部按钮点不到。这里用 Canvas + 内嵌 Frame + Scrollbar 解决。

        页面里 `_page_xxx(parent)` 照旧往里 pack 就行，不用改。
        """
        outer = tk.Frame(parent, bg=COLOR["bg_root"])
        outer.pack(side="left", fill="both", expand=True, padx=(0, 14), pady=(0, 8))

        self._scroll_canvas = tk.Canvas(outer, bg=COLOR["bg_root"],
                                        highlightthickness=0, bd=0)
        self._scroll_canvas.pack(side="left", fill="both", expand=True)

        self._vbar = tk.Scrollbar(outer, orient="vertical",
                                  command=self._scroll_canvas.yview,
                                  width=10, bd=0, relief="flat",
                                  troughcolor=COLOR["bg_root"],
                                  bg=COLOR["border"],
                                  activebackground=COLOR["brand"],
                                  highlightthickness=0)
        # 初始隐藏，内容超出时才显示
        self._vbar_visible = False

        self._scroll_canvas.configure(yscrollcommand=self._on_scroll_set)

        # ★ 页面容器：各 `_page_xxx` 都 pack 到这里
        self.content = tk.Frame(self._scroll_canvas, bg=COLOR["bg_root"])
        self._scroll_win = self._scroll_canvas.create_window(
            (0, 0), window=self.content, anchor="nw")

        # 内容尺寸变化 → 更新滚动区域 + 是否需要滚动条
        # ★★ 必须用守卫版（theme.bind_configure）：直接在 <Configure> 里改
        #    Canvas 配置会**再触发一次 <Configure>**，macOS 上就变成
        #    "Configure → 改配置 → Configure" 死循环 —— 实测主线程卡在
        #    `self._scroll_canvas.configure(...)` 这一行，永远回不到事件循环。
        bind_configure(self.content, self._on_content_configure)
        bind_configure(self._scroll_canvas,
                       lambda: self._set_scroll_width(
                           self._scroll_canvas._cfg_w))

        # 滚轮（含日志面板等区域，用 bind_all 会互相抢，这里只绑画布与内容）
        # ★ 用 theme.bind_wheel：跨平台（Win/mac 的 <MouseWheel> + Linux 的
        #   <Button-4/5>）——之前只绑 <MouseWheel>，Linux 上完全滚不动。
        for w in (self._scroll_canvas, self.content):
            bind_wheel(w, self._on_mousewheel)
            w.bind("<Enter>", lambda e: self._bind_wheel_all())
            w.bind("<Leave>", lambda e: self._unbind_wheel_all())

    # ------------------------------------------ 滚动逻辑

    def _on_content_configure(self, _event=None):
        try:
            self._scroll_canvas.configure(
                scrollregion=self._scroll_canvas.bbox("all"))
        except Exception:
            pass

    def _set_scroll_width(self, width: int):
        """内嵌窗口宽度跟随画布，保证 fill="x" 的卡片能撑满。

        （原来是 `_on_canvas_configure(event)`，现在由守卫版绑定调用，
          尺寸从 `_cfg_w` 拿。）
        """
        try:
            self._scroll_canvas.itemconfig(self._scroll_win, width=width)
        except Exception:
            pass

    def _on_canvas_configure(self, event):
        """保留老接口（守卫版绑定已经不走它了）。"""
        self._set_scroll_width(event.width)

    def _on_scroll_set(self, first, last):
        """内容超高时才挂滚动条。"""
        try:
            need = not (float(first) <= 0.0 and float(last) >= 1.0)
        except Exception:
            need = True
        if need and not self._vbar_visible:
            self._vbar.pack(side="right", fill="y", padx=(2, 0))
            self._vbar_visible = True
        elif not need and self._vbar_visible:
            self._vbar.pack_forget()
            self._vbar_visible = False
        self._vbar.set(first, last)

    def _bind_wheel_all(self):
        bind_wheel_all(self, self._on_mousewheel)

    def _unbind_wheel_all(self):
        unbind_wheel_all(self)

    def _on_mousewheel(self, event):
        """★ 智能滚轮：只有内容真的超出时才滚，否则把事件交给别的控件。

        ★ 跨平台步长由 `theme.wheel_units` 统一换算 —— 之前写死
          `int(-event.delta / 120)` 是 Windows 量纲，macOS 上 delta 只有 ±1，
          除完恒为 0，**滚轮完全失效**（用户报「只能拖滚动条」的根因）。
        """
        try:
            first, last = self._scroll_canvas.yview()
            if first <= 0.0 and last >= 1.0:
                return          # 内容没超出，不滚
            units = wheel_units(event)
            if units:
                self._scroll_canvas.yview_scroll(units, "units")
        except Exception:
            pass

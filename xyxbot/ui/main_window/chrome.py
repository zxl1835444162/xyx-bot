"""顶栏 / 侧栏 / 日志面板。

由 `xyxbot/ui/main_window.py` 拆分而来（class split）：只搬位置、
不改逻辑（方法体、注释、装饰器、超时值全部原样）。
"""

from __future__ import annotations

from xyxbot.ui.defaults import (APP_NAME, COMPANY, DEFAULT_PAGE, EXTRA_PAGES,
                       NAV_ITEMS, PAGE_ALIASES, VERSION)
from xyxbot.ui.theme import (COLOR, F, BrandButton, CheckBox, GradientBar, LogView,
                    StatusBar, bind_configure, bind_wheel, bind_wheel_all,
                    round_rect, unbind_wheel_all, wheel_units)
import tkinter as tk

from xyxbot.ui.main_window.nav_item import NavItem


class ChromeMixin:
    """顶栏 / 侧栏 / 日志面板。"""

    # ------------------------------------------------------------ 顶栏

    def _build_topbar(self):
        bar = tk.Frame(self, bg=COLOR["bg_titlebar"], height=64)
        bar.pack(fill="x")
        bar.pack_propagate(False)

        # 渐变条放在底边
        grad = GradientBar(bar, height=2,
                           colors=["#1a1206", "#d4a24c", "#d4a24c", "#1a1206"])
        grad.pack(side="bottom", fill="x")

        left = tk.Frame(bar, bg=COLOR["bg_titlebar"])
        left.pack(side="left", fill="y", padx=18)

        # 徽标
        logo = tk.Canvas(left, width=38, height=38, bg=COLOR["bg_titlebar"],
                         highlightthickness=0, bd=0)
        logo.pack(side="left", pady=13)
        round_rect(logo, 1, 1, 37, 37, 9, fill=COLOR["brand"], outline="")
        logo.create_text(19, 19, text="赵", font=F(15, True),
                         fill=COLOR["text_on_brand"])

        namebox = tk.Frame(left, bg=COLOR["bg_titlebar"])
        namebox.pack(side="left", padx=(10, 0), pady=13)
        tk.Label(namebox, text=APP_NAME, font=F(13, True),
                 bg=COLOR["bg_titlebar"], fg=COLOR["text"]).pack(anchor="w")
        tk.Label(namebox, text=f"{COMPANY}  ·  AI 内容工业化生产平台",
                 font=F(8), bg=COLOR["bg_titlebar"],
                 fg=COLOR["brand"]).pack(anchor="w")

        # 右侧：用户信息
        # ★ 2026-10-04 按用户要求删掉登录界面 —— 没有登录了，"退出登录"
        #   这个按钮也就没有意义，一并去掉（关窗即退出程序）。
        right = tk.Frame(bar, bg=COLOR["bg_titlebar"])
        right.pack(side="right", fill="y", padx=18)

        userbox = tk.Frame(right, bg=COLOR["bg_titlebar"])
        userbox.pack(side="right", padx=(0, 14), pady=16)
        tk.Label(userbox, text=self._username, font=F(10, True),
                 bg=COLOR["bg_titlebar"], fg=COLOR["text"]).pack(anchor="e")
        tk.Label(userbox, text="已授权  ·  Enterprise", font=F(8),
                 bg=COLOR["bg_titlebar"], fg=COLOR["success"]).pack(anchor="e")

        # 头像
        av = tk.Canvas(right, width=34, height=34, bg=COLOR["bg_titlebar"],
                       highlightthickness=0, bd=0)
        av.pack(side="right", padx=(0, 12), pady=15)
        av.create_oval(1, 1, 33, 33, fill=COLOR["bg_card_hi"],
                       outline=COLOR["brand"], width=1)
        av.create_text(17, 17, text=self._username[:1].upper(),
                       font=F(12, True), fill=COLOR["brand"])

    # ------------------------------------------------------------ 侧边栏

    def _build_sidebar(self, parent):
        side = tk.Frame(parent, bg=COLOR["bg_root"], width=176)
        side.pack(side="left", fill="y", padx=14, pady=(12, 8))
        side.pack_propagate(False)

        for key, icon, label in NAV_ITEMS:
            item = NavItem(side, icon=icon, text=label,
                           command=lambda k=key: self.show_page(k))
            item.pack(fill="x", pady=2)
            self._nav_buttons[key] = item

    # ------------------------------------------------------------ 日志面板

    def _build_log_panel(self):
        wrap = tk.Frame(self, bg=COLOR["bg_root"])
        wrap.pack(side="bottom", fill="x", padx=14, pady=(0, 6))

        head = tk.Frame(wrap, bg=COLOR["bg_root"])
        head.pack(fill="x")

        self._log_toggle = tk.Label(
            head, text="▾  运行日志", font=F(9, True),
            bg=COLOR["bg_root"], fg=COLOR["text_dim"], cursor="hand2",
        )
        self._log_toggle.pack(side="left")
        self._log_toggle.bind("<Button-1>", lambda e: self._toggle_log())

        BrandButton(head, "清空", command=lambda: self.log_view.clear(),
                    width=56, height=24, style="ghost",
                    bg=COLOR["bg_root"], font_size=8).pack(side="right")

        # ★★ 「只看关键节点」（2026-10-04）：跑 100 章会产生几百行日志，
        #   大部分是"切换页面"这类过程噪音；真正要看的是**每章的结果**。
        #   勾上以后噪音行被 Tk 的 elide 折叠（内容还在，取消勾选立刻全回来）。
        self._log_keyonly = CheckBox(
            head, "只看关键节点", checked=False,
            command=lambda v: self._set_log_keyonly(bool(v)),
            width=150, height=24, bg=COLOR["bg_root"])
        self._log_keyonly.pack(side="right", padx=(0, 10))

        self.log_view = LogView(wrap, height=7)
        self.log_view.pack(fill="x", pady=(6, 0))

        self.log("系统就绪 · 欢迎使用 %s %s" % (APP_NAME, VERSION), "brand")
        self.log("提示：默认页就是「跑章」—— 配置好之后点左上角「开始跑章」即可", "info")

    def _set_log_keyonly(self, on: bool):
        """切换日志过滤（噪音行折叠 / 展开）。"""
        if not hasattr(self, "log_view"):
            return
        try:
            self.log_view.set_key_only(bool(on))
        except Exception:
            return
        if on:
            self.log("（已开启「只看关键节点」：过程日志被折叠，"
                     "取消勾选即可全部展开）", "info")

    def _toggle_log(self):
        if self._log_visible:
            self.log_view.pack_forget()
            self._log_toggle.configure(text="▸  运行日志")
        else:
            self.log_view.pack(fill="x", pady=(6, 0))
            self._log_toggle.configure(text="▾  运行日志")
        self._log_visible = not self._log_visible

"""主界面：赵氏集团 · 星月创作台。

布局参考 novel-publisher 的分区思路（配置 / 操作 / 日志），
但视觉上重做为现代深色仪表盘：

    ┌─────────────────────────────────────────────┐
    │  顶栏：品牌 + 用户 + 状态                     │
    ├──────────┬──────────────────────────────────┤
    │ 侧边导航  │  内容区（概览 / 任务 / 配置 / 关于）│
    │          │                                  │
    ├──────────┴──────────────────────────────────┤
    │  日志面板（可折叠）                            │
    ├─────────────────────────────────────────────┤
    │  状态栏                                       │
    └─────────────────────────────────────────────┘
"""

from __future__ import annotations

import re
import tkinter as tk
from typing import Callable, Optional

from .browser_session import BrowserSession
from .defaults import (APP_NAME, COMPANY, DEFAULT_PAGE, EXTRA_PAGES,
                       NAV_ITEMS, PAGE_ALIASES, VERSION)
from .pages import (AboutPage, AccountPage, AiFlowMixin, BooksPage,
                    ChaptersMixin, ConfigIOMixin, MorePage, OverviewPage,
                    RunMixin, SettingsPage, SetupMixin, TasksPage)
from .theme import (COLOR, F, BrandButton, CheckBox, GradientBar, LogView,
                    StatusBar, bind_configure, round_rect)

class MainWindow(AboutPage, AccountPage, AiFlowMixin, BooksPage,
                 ChaptersMixin, ConfigIOMixin, MorePage, OverviewPage,
                 RunMixin, SettingsPage, SetupMixin, TasksPage, tk.Toplevel):
    """主窗口。

    ★ 架构改良（阶段二）：页面构建与业务动作已按「一页/一块一模块」拆到
    `ui/pages/`，以 mixin 方式组合（见 `ui/pages/__init__.py` 的模块一览）。
    本文件只保留：窗口骨架（顶栏/侧栏/滚动区/日志面板/状态栏）、
    页面路由（`show_page`）、浏览器生命周期、任务执行与互斥、关窗清理。

    ★★ 界面重设计（2026-10-04）：主导航从 7 项收敛成 3 项
    （跑章 / 准备 / 更多），并把 `show_page` 从「每次销毁重建」改成
    「构建一次、之后只显示/隐藏」—— 后者修掉了两个真实缺陷：
      ① 切页会丢掉没保存的编辑（模板/细纲都是从 workspace.json 回填的）；
      ② 后台任务回调里持有的按钮引用会变成已销毁控件（报 TclError）。

    ★★★ 为什么是 `tk.Toplevel` 而不是 `tk.Tk`（2026-10-04，真机复现）
    =====================================================================
    在 macOS 上，**一个进程里第 2 个 `tk.Tk()` 的 `mainloop()` 收不到任何
    事件**：窗口不绘制、`after` 定时器不触发、鼠标一直转圈，而且不抛异常。
    用户看到的就是「点登录后登录窗消失、鼠标转圈、主界面永远不出来」。

    实测（GitHub 的 macOS runner）：
        ★ 卡死了：主线程已 20.4 秒没有任何进展
           最后一次进展：MainWindow.__init__ 结束   ← 窗口建好了
           平台：darwin                              ← 它的 mainloop 不工作
        而第 1 个 root（登录窗）的 after 回调是正常触发的。

    所以整个程序只允许一个 `tk.Tk()`（由 `run_gui.run_app` 建并 withdraw
    当宿主），登录窗/主界面都是它的 Toplevel。
    `master=None` 时自动建一个自己的 root，兼容单独使用与单元测试。
    """

    def __init__(self, master=None, username: str = "用户",
                 on_logout: Optional[Callable[[], None]] = None,
                 on_quit: Optional[Callable[[], None]] = None):
        # ★ 兼容老写法：不传 master 就自己建一个 root（并藏起来）
        if master is None:
            master = tk.Tk()
            try:
                master.withdraw()
            except Exception:
                pass
            self._owns_root = True
        else:
            self._owns_root = False
        super().__init__(master)
        self._username = username
        self._on_logout = on_logout
        # ★ 用户点关闭按钮时通知外层（外层负责结束事件循环）。
        #   没有它的话，单 root 架构下关掉主界面后事件循环还在跑，
        #   程序会变成一个"看不见却活着"的进程。
        self._on_quit = on_quit
        self._app = None          # 自动化 App 实例（懒启动）
        self._current = DEFAULT_PAGE
        self._nav_buttons: dict[str, NavItem] = {}
        # ★ 已构建的页面 {key: Frame}（构建一次，之后只 pack/pack_forget）
        self._pages: dict[str, tk.Frame] = {}
        self._log_visible = True
        self._login_running = False   # 登录流程是否进行中
        self._login_stop = None       # 通知登录线程「用户已确认登录」

        # ★★ 常驻 Playwright 线程（2026-10-04 关键修复）：
        #   Playwright 的浏览器对象（page/context）**必须一直在同一个线程里操作**，
        #   不能跨线程。之前每个按钮各自新开线程 → 谁先开浏览器，浏览器就「绑」在
        #   谁的线程上；线程一退出，再点别的按钮就会报
        #   `cannot switch to a different thread (which happens to have exited)`。
        #
        #   ★ 架构改良：这块基础设施已抽到 `ui/browser_session.py` 的
        #   `BrowserSession`（不含任何 tkinter 依赖、可独立测试）。
        #   所有浏览器任务统一走 `self.session.submit(...)`。
        self.session = BrowserSession(log=self._session_log,
                                      app_factory=self._make_app)

        # ★★ 统一任务互斥（用户 2026-10-03 需求）：
        #   一次只跑一个「操作浏览器」的任务，避免多个后台线程并发操作
        #   同一个 Playwright page → 报「线程被占用/导航冲突」这类底层错。
        #   互斥状态现在由 `self.session`（BrowserSession）持有；
        #   这里保留两个只读代理属性以兼容既有页面代码。

        # ★ 「运行配置」页填的浏览器路径（切页会销毁控件，所以值单独存一份）
        self._browser_path_value = ""

        self.title(f"{COMPANY} · {APP_NAME}")
        self.configure(bg=COLOR["bg_root"])
        self.geometry("1180x820")
        self.minsize(1040, 700)
        self._center(1180, 820)
        # ★ 记住上次的窗口大小/位置（可用就覆盖上面的默认值）
        self._restore_geometry()

        # ★ 关窗时清理浏览器进程（否则会残留 Playwright 子进程）
        self.protocol("WM_DELETE_WINDOW", self._on_window_close)

        self._build()

        # ★ 最后把窗口显式"推"到用户面前（见 _present 的说明）
        self._present()

    def _present(self):
        """确保主窗口真的显示出来、并且在最前面。

        ★★ 为什么需要（2026-10-04 用户在 macOS 上反馈「输完授权码进不去」）
        =====================================================================
        真实流程是：

            登录窗（第一个 Tk root）→ destroy → 主界面（第二个 Tk root）

        在 macOS 的 Aqua Tk 上，**销毁再新建 root** 之后，新窗口有时不会
        自动显示到前台（Windows 上一般没这个问题）。用户看到的就是
        「登录窗没了、主界面不出现、也没有任何报错」。

        这里显式 deiconify + lift + 短暂置顶 + 抢一次焦点，把这件事按死。
        置顶只保持 400ms 就撤掉，避免长期霸占最前面。
        """
        try:
            self.deiconify()
        except Exception:
            pass
        try:
            self.lift()
        except Exception:
            pass
        try:
            self.attributes("-topmost", True)

            def _unpin():
                # 万一这 400ms 内用户已经点了任务（任务会主动置顶），就别撤
                if not getattr(self, "_topmost_on", False):
                    try:
                        self.attributes("-topmost", False)
                    except Exception:
                        pass

            self.after(400, _unpin)
        except Exception:
            pass
        try:
            self.focus_force()
        except Exception:
            pass

    # ------------------------------------------------------------ 基础

    def _center(self, w: int, h: int):
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        x = int((sw - w) / 2)
        y = int((sh - h) / 3)
        self.geometry(f"{w}x{h}+{x}+{max(0, y)}")

    # ------------------------------------------------------------ ★ 窗口记忆

    def _restore_geometry(self):
        """恢复上次的窗口大小/位置。

        ★ 必须做**可见性校验**：万一上次是在副屏/更大分辨率下存的，
          直接照搬会把窗口放到看不见的地方（用户会以为程序没启动）。
          所以位置要夹到当前屏幕内，尺寸也要夹到屏幕大小以内。
        """
        try:
            from src.workspace import load_ws
            geo = str(load_ws().get("win_geometry") or "").strip()
        except Exception:
            return
        m = re.match(r"^(\d+)x(\d+)([+-]\d+)([+-]\d+)$", geo)
        if not m:
            return
        w, h, x, y = (int(m.group(1)), int(m.group(2)),
                      int(m.group(3)), int(m.group(4)))
        try:
            sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        except Exception:
            return
        if w < 800 or h < 600 or w > sw * 2 or h > sh * 2:
            return
        # 尺寸不超屏；位置保证标题栏和左侧至少有一部分在屏内
        w = min(w, sw)
        h = min(h, sh)
        x = max(-w + 200, min(x, sw - 120))
        y = max(0, min(y, sh - 60))
        try:
            self.geometry(f"{w}x{h}+{x}+{y}")
        except Exception:
            pass

    def _save_geometry(self) -> None:
        """记下当前窗口大小/位置。"""
        try:
            from src.workspace import save_ws
            save_ws(win_geometry=self.winfo_geometry())
        except Exception:
            pass

    def _build(self):
        # 顶栏
        self._build_topbar()

        # 主体：左导航 + 右内容
        body = tk.Frame(self, bg=COLOR["bg_root"])
        body.pack(fill="both", expand=True)

        self._build_sidebar(body)

        # 内容区：Canvas + 滚动条，整页可上下滚动
        self._build_scroll_area(body)

        # 日志面板
        self._build_log_panel()

        # 状态栏
        self.status = StatusBar(self, version=f"{COMPANY}  ·  {VERSION}")
        self.status.pack(side="bottom", fill="x")

        # 默认页
        self.show_page(DEFAULT_PAGE)

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
        for w in (self._scroll_canvas, self.content):
            w.bind("<MouseWheel>", self._on_mousewheel)
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
        self.bind_all("<MouseWheel>", self._on_mousewheel)

    def _unbind_wheel_all(self):
        self.unbind_all("<MouseWheel>")

    def _on_mousewheel(self, event):
        """★ 智能滚轮：只有内容真的超出时才滚，否则把事件交给别的控件。"""
        try:
            first, last = self._scroll_canvas.yview()
            if first <= 0.0 and last >= 1.0:
                return          # 内容没超出，不滚
            self._scroll_canvas.yview_scroll(int(-event.delta / 120), "units")
        except Exception:
            pass

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

        # 右侧：用户 + 登出
        right = tk.Frame(bar, bg=COLOR["bg_titlebar"])
        right.pack(side="right", fill="y", padx=18)

        BrandButton(right, "退出登录", command=self._logout, width=88,
                    height=32, style="ghost", bg=COLOR["bg_titlebar"],
                    font_size=9).pack(side="right", pady=16)

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

    # ------------------------------------------------------------ 页面切换

    # 页面 key → 标签（导航项 + 额外页面 + 别名）
    def _page_labels(self) -> dict:
        d = {k: l for k, _i, l in NAV_ITEMS}
        d.update(EXTRA_PAGES)
        for old, new in PAGE_ALIASES.items():
            d[old] = d.get(new, new)
        return d

    def _page_builders(self) -> dict:
        """页面 key → 构建函数。

        ★ 原来 `content`（小说分章）页被拆成「跑章」+「准备」两部分；
          旧 key 通过 `PAGE_ALIASES` 落到 `run`，所以旧代码/链接不会 404。
        """
        return {
            # ---- 主导航三项 ----
            "run": self._page_run,
            "setup": self._page_setup,
            "more": self._page_more,
            # ---- 从导航撤下来、但「更多」页仍可进入的旧页面 ----
            "overview": self._page_overview,
            "account": self._page_account,
            "books": self._page_books,
            "tasks": self._page_tasks,
            "settings": self._page_settings,
            "about": self._page_about,
        }

    def show_page(self, key: str):
        key = PAGE_ALIASES.get(key, key)
        if key not in self._page_builders():
            self.log(f"未知页面：{key}", "warn")
            return

        for k, btn in self._nav_buttons.items():
            btn.set_active(k == key)
        self._current = key

        # ★★ 构建一次、之后只显示/隐藏（2026-10-04 界面重设计）
        #
        #   原实现每次切页都 `destroy()` 掉整页控件再重建，带来两个真实缺陷：
        #     ① **切页会丢编辑** —— 指令模板、章节细纲、跑章参数都没保存就没了
        #        （回来后是从 workspace.json 回填的旧值）；
        #     ② **后台任务回调炸控件** —— 任务里 `self.after(0, btn.set_text, …)`
        #        持有的按钮已被销毁，触发 TclError。
        #   页面只有 3~9 个，一次构建常驻的成本可以忽略。
        frame = self._pages.get(key)
        if frame is None:
            frame = tk.Frame(self.content, bg=COLOR["bg_root"])
            try:
                self._page_builders()[key](frame)
            except Exception as e:
                frame.destroy()
                import traceback
                self.log(f"页面「{self._page_labels().get(key, key)}」构建失败：{e}",
                         "err")
                self.log(traceback.format_exc().splitlines()[-1], "err")
                return
            self._pages[key] = frame

        for k, f in self._pages.items():
            try:
                if k == key:
                    f.pack(fill="both", expand=True)
                else:
                    f.pack_forget()
            except Exception:
                continue

        # 切页后回到顶部
        try:
            self._scroll_canvas.yview_moveto(0)
            self.after(60, lambda: self._scroll_canvas.yview_moveto(0))
            self.after(200, self._on_content_configure)
        except Exception:
            pass

        self.log(f"切换页面：{self._page_labels().get(key, key)}", "info")

    # ------------------------------------------------------------ 各页面

    def _page_header(self, parent, title: str, sub: str):
        box = tk.Frame(parent, bg=COLOR["bg_root"])
        box.pack(fill="x", pady=(6, 12))
        tk.Label(box, text=title, font=F(17, True),
                 bg=COLOR["bg_root"], fg=COLOR["text"]).pack(anchor="w")
        tk.Label(box, text=sub, font=F(9),
                 bg=COLOR["bg_root"], fg=COLOR["text_dim"]).pack(anchor="w", pady=(3, 0))

    # ---- 登录流程（关键：登录不限时，随时可手动确认保存）----

    # ------------------------------------------------ ★ 流程准备（一条龙前置）
    #
    #  用户需求（2026-10-03）：
    #    在所有的流程开始之前，有一个打开网站提前配置，
    #    然后进行 cookie 或者缓存保存的功能，
    #    然后之后点击一条龙服务，就直接开始。

    def _ensure_app(self):
        """按需创建并启动 App（浏览器）。已有的直接复用。

        ★ 只能在常驻 Playwright 线程里调用（即从 `self.session.submit(...)`
        投递进来的 worker 中）。
        实现委托给 `BrowserSession.ensure_app()`。
        """
        app = self.session.ensure_app()
        self._app = app          # 兼容旧字段（页面代码里还在读 self._app）
        return app

    def _browser_path_override(self):
        """读「运行配置」页里用户填的浏览器路径（留空 = 自动检测）。

        ★ 读的是持久字段 `_browser_path_value`，不是控件 ——
          因为切页会销毁 `_browser_entry`，随后启动浏览器时控件已不存在。
        """
        try:
            if self._browser_entry.winfo_exists():
                self._browser_path_value = (
                    self._browser_entry.get() or "").strip().strip('"')
        except Exception:
            pass          # 控件已销毁 → 沿用上次记录的值
        return self._browser_path_value or None

    def _stop_app(self):
        """★ 线程安全地关掉 App（浏览器）。

        ★ 根因修复（跨线程 bug）：
          `App` / `browser` / `context` 是在**常驻 Playwright 线程**里创建的，
          而 `App.stop()` 会 close context 并停掉 playwright ——
          如果直接在 Tk 主线程调用，就违反「Playwright 对象必须同线程操作」
          这条铁律（源码在 `__init__` 的注释里已明确写下），
          轻则报 `cannot switch to a different thread`，重则与队列里
          尚未执行的任务竞争。

          实现委托给 `BrowserSession.stop()`：它把 `app.stop()` 投递到
          常驻线程里执行，并立刻断开引用避免后续任务复用。
        """
        self._app = None
        self.session.stop(
            on_done=lambda e: self._session_log(
                f"关闭浏览器时出错（忽略）：{e}", "warn"))

    # ------------------------------------------------------------ 打开作品

    # -------------------------------------------------- 一步到位：打开作品

    # -------------------------------------------------- 同名候选

    # -------------------------------------------------- 查看全部

    def _ensure_page(self):
        """确保 App 与浏览器已启动，返回 page（阻塞，供后台线程调用）。"""
        from src.app import App

        if self._app is None:
            self._app = App(headless=False,
                                    browser_path=self._browser_path_override())
            self._app.start(with_log_file=True)
        return self._app.page

    # -------------------------------------------------- 工作区配置

    # -------------------------------------------------- 选文件 / 分章

    # -------------------------------------------------- ★ 指令模板

    # -------------------------------------------------- 一键 AI 续写

    # -------------------------------------------------- AI 审稿

    # -------------------------------------------------- ★ 续写 + 审稿 一条龙

    # -------------------------------------------------- ★ 批量跑章

    # -------------------------------------------------- 保存 / 读取工程

    # ------------------------------------------------------------ 交互

    def _task_names(self) -> list[str]:
        try:
            from src.tasks import list_task_names
            return list_task_names()
        except Exception:
            return []

    def _run_task(self, name: str):
        """★ 执行注册任务（走统一互斥锁 + 常驻 Playwright 线程）。

        ★ 根因修复（跨线程 bug）：
          `_run_guarded` 已经保证 `worker` 会跑在常驻 `pw-worker` 线程上，
          所以这里**不要**再自己建 App ——直接用 `self._ensure_app()` 即可。
          原实现在 worker 里 `App(...).start()`，虽然恰好也在 pw 线程
          （因为 `_run_guarded` 投递了它），但绕过了 `_ensure_app` 的统一入口，
          容易在后续改动中被误放到别的线程；这里统一走 `_ensure_app`。
        """
        self.log(f"准备执行任务：{name}", "brand")
        self.status.set_status(f"执行中：{name}", "warn")
        # 任务会把浏览器窗口拉到前台，这里保持主窗口可见
        self._keep_on_top(True)

        def worker():
            try:
                from src.logging_redirect import LogRedirector

                app = self._ensure_app()

                # 把后端 print 重定向到 UI 日志
                redirector = LogRedirector(
                    sink=lambda m: self.after(0, self.log, m, "info")
                ).install()
                try:
                    ok = app.run_task(name)
                finally:
                    redirector.restore()

                level = "ok" if ok else "err"
                msg = f"任务完成：{name}" if ok else f"任务结束（未成功）：{name}"
                self.after(0, self.log, msg, level)
                self.after(0, self.status.set_status, msg, level)
            except Exception as e:
                self.after(0, self.log, f"任务异常：{e}", "err")
                self.after(0, self.status.set_status, f"异常：{e}", "err")
            finally:
                self.after(0, self._keep_on_top, False)

        # ★ 统一互斥：上一个任务没跑完就再点 → 友好提示，不并发操作浏览器
        self._run_guarded(name, worker)

    def _keep_on_top(self, on: bool):
        """任务期间让主窗口保持置顶，避免被浏览器窗口遮挡。"""
        self._topmost_on = bool(on)
        try:
            self.attributes("-topmost", bool(on))
            if on:
                self.lift()
        except Exception:
            pass

    # -------------------------------------------------- ★ 常驻 Playwright 线程
    #
    #  ★ 架构改良（2026-10-04）：线程模型 / 任务队列 / 互斥锁已抽到
    #    `ui/browser_session.py` 的 `BrowserSession`（无 tkinter 依赖、可单测）。
    #    下面这些方法保留为**薄封装**，让既有页面代码无需改动即可平滑迁移；
    #    新代码请直接使用 `self.session.*`。

    def _make_app(self):
        """App 工厂（只在常驻 Playwright 线程里被 BrowserSession 调用）。"""
        from src.app import App
        return App(headless=False,
                   browser_path=self._browser_path_override())

    def _session_log(self, msg: str, level: str = "info"):
        """BrowserSession 的日志回调 —— 从常驻线程安全地转到 tk 主线程。"""
        try:
            self.after(0, self.log, msg, level)
        except Exception:
            pass

    def _run_guarded(self, name: str, worker_fn, btn=None) -> bool:
        """★★ 统一的「后台跑浏览器任务」入口：互斥 + 状态 + 按钮管理。

        实现已迁移到 `BrowserSession.run_guarded`。这里只负责
        **按钮态的 tk 侧处理**（运行中禁用、完成恢复）。

        ★ 顺带修复：按钮禁用改用 `set_enabled()`。
          原实现用 `btn.config(state="disabled")`，但 BrandButton 是
          tk.Canvas，外层 state 不会拦截 `<Button-1>` 绑定 ——
          视觉变灰、实际仍可点击，忙碌期间会重复触发任务。
          （同时 theme.BrandButton.config 也已支持 state 转发，双保险。）
        """
        if btn is not None:
            try:
                if hasattr(btn, "set_enabled"):
                    btn.set_enabled(False)
                else:
                    btn.config(state="disabled")
            except Exception:
                pass

        def _restore():
            if btn is None:
                return
            try:
                if hasattr(btn, "set_enabled"):
                    btn.set_enabled(True)
                else:
                    btn.config(state="normal")
            except Exception:
                pass

        started = self.session.run_guarded(name, worker_fn, on_done=_restore)
        if not started:
            # 被拒绝（已有任务在跑）→ 把刚禁用的按钮立刻恢复
            _restore()
        return started

    # ------------------------------------------------------------ 对外

    def log(self, msg: str, level: str = "info"):
        self.log_view.log(msg, level)

    def _teardown(self, *, closing: bool):
        """★ 关窗 / 退登**共用**的清理：先落盘，再关浏览器，最后销毁并通知外层。

        ★ 2026-10-04：关窗前把「该记住的东西」落盘 —— 窗口大小/位置 +
          界面配置 + 小说轻量记忆（细纲）。否则用户填完细纲直接关窗就丢了。

        ★ 根因修复（更早）：原来既没有 `WM_DELETE_WINDOW` 绑定，`_logout` 也不调
          `App.stop()` → 直接关窗会**残留 Playwright 浏览器进程**。

        Args:
            closing: True = 用户关窗（要退出程序）；False = 退出登录（回登录窗）。
        """
        # ① 先存（此时控件还在，能读到值）
        try:
            self._save_geometry()
        except Exception:
            pass
        try:
            self._save_ws(silent=True)
        except Exception:
            pass
        try:
            if hasattr(self, "_save_last_project"):
                self._save_last_project()
        except Exception:
            pass
        # ② 再关浏览器
        try:
            self._stop_app()
        except Exception:
            pass
        # ③ 销毁窗口
        try:
            self.destroy()
        except Exception:
            pass
        # ④ 通知外层（★ 单 root 架构下这一步是必须的：窗口都没了，
        #    事件循环还活着的话程序就变成"看不见却活着"）
        try:
            if closing:
                if self._on_quit:
                    self._on_quit()
            else:
                if self._on_logout:
                    self._on_logout()
        except Exception:
            pass

    def _on_window_close(self):
        """用户点了窗口关闭按钮（红叉）→ 清理并退出程序。"""
        self._teardown(closing=True)

    def _logout(self):
        """点了「退出登录」→ 清理并回到登录窗（**不退出程序**）。"""
        self._teardown(closing=False)


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



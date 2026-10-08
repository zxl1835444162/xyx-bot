"""窗口骨架：初始化、放置/居中、几何记忆、构建与收尾。

由 `xyxbot/ui/main_window.py` 拆分而来（class split）：只搬位置、
不改逻辑（方法体、注释、装饰器、超时值全部原样）。
"""

from __future__ import annotations

from typing import Callable, Optional
from xyxbot.ui.browser_session import BrowserSession
from xyxbot.ui.defaults import (APP_NAME, COMPANY, DEFAULT_PAGE, EXTRA_PAGES,
                       NAV_ITEMS, PAGE_ALIASES, VERSION)
from xyxbot.ui.theme import (COLOR, F, BrandButton, CheckBox, GradientBar, LogView,
                    StatusBar, bind_configure, bind_wheel, bind_wheel_all,
                    round_rect, unbind_wheel_all, wheel_units)
import re
import tkinter as tk

from xyxbot.ui.main_window.nav_item import NavItem


class WindowMixin:
    """窗口骨架：初始化、放置/居中、几何记忆、构建与收尾。"""

    def __init__(self, master=None, username: str = "本机用户",
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
            from xyxbot.workspace import load_ws
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
            from xyxbot.workspace import save_ws
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

    def _keep_on_top(self, on: bool):
        """任务期间让主窗口保持置顶，避免被浏览器窗口遮挡。"""
        self._topmost_on = bool(on)
        try:
            self.attributes("-topmost", bool(on))
            if on:
                self.lift()
        except Exception:
            pass

    def _teardown(self):
        """★ 关窗清理：先落盘，再关浏览器，最后销毁窗口并通知外层。

        ★ 2026-10-04：关窗前把「该记住的东西」落盘 —— 窗口大小/位置 +
          界面配置 + 小说轻量记忆（细纲）。否则用户填完细纲直接关窗就丢了。

        ★ 根因修复（更早）：原来既没有 `WM_DELETE_WINDOW` 绑定，也没有
          `App.stop()` → 直接关窗会**残留 Playwright 浏览器进程**。

        ★ 2026-10-04 删掉登录界面后：不再有"退出登录回登录窗"这条路，
          关窗就是退出程序（所以不再需要 `closing` 参数）。
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
            if self._on_quit:
                self._on_quit()
        except Exception:
            pass

    def _on_window_close(self):
        """用户点了窗口关闭按钮（红叉）→ 清理并退出程序。

        ★ 2026-10-04 删掉登录界面后，关窗就是**退出程序**（不再有"回到登录窗"）。
        """
        self._teardown()

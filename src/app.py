"""App 主类：把浏览器、平台、任务串起来。

对应参考项目的 NovalPublisherApp，但去掉了 tkinter 依赖 ——
所有任务函数签名 func(app) 里的 app 就是本类实例。
"""

from __future__ import annotations

from typing import Optional

from . import config as C
from .browser import open_browser, open_persistent
from .logging_redirect import LogRedirector, default_log_file


class App:
    """应用上下文。

    用法：
        app = App()
        app.start()
        app.run_task("打开创作台")
        app.stop()
    """

    def __init__(self, browser_path: Optional[str] = None,
                 headless: bool = False, use_persistent: bool = False):
        self.browser_path = browser_path or C.BROWSER_PATH
        self.headless = headless
        self.use_persistent = use_persistent

        self._pw = None
        self.browser = None
        self.context = None
        self.log_redirector: Optional[LogRedirector] = None

    # ------------------------------------------------ 生命周期

    def start(self, with_log_file: bool = True) -> "App":
        from playwright.sync_api import sync_playwright

        self._pw = sync_playwright().start()

        if self.use_persistent:
            self.browser, self.context = open_persistent(
                self._pw, C.USER_DATA_DIR, headless=self.headless,
                browser_path=self.browser_path,
            )
            self._persistent = True
        else:
            # ★ 根因修复：`config.CDP_PORT` 原本**定义了却无人引用** →
            #   README 第十节大书特书的「CDP 接管最强风控方案」在 CLI/GUI 里
            #   根本没有入口，必须手动把 browser_path 传成端口号才行。
            #   现在：设了 `XYX_CDP_PORT` 就自动走接管模式（显式 browser_path 优先）。
            cdp_port = None
            if not self.browser_path and getattr(C, "CDP_PORT", None):
                cdp_port = str(C.CDP_PORT).strip()
                if cdp_port:
                    print(f"[app] 检测到 XYX_CDP_PORT={cdp_port} → 启用浏览器接管模式")
            self.browser, self.context = open_browser(
                p=self._pw,
                custom_browser_path=self.browser_path or cdp_port,
                headless=self.headless,
                auth_file=C.STATE_FILE,
            )
            self._persistent = False

        if self.context is None:
            raise RuntimeError("浏览器启动失败")

        if with_log_file:
            self.log_redirector = LogRedirector(log_file=default_log_file()).install()

        print(f"已启动：{C.SITE['name']} 自动化会话")
        return self

    def stop(self) -> None:
        try:
            if self.context:
                self.context.close()
        except Exception:
            pass
        try:
            if self._pw:
                self._pw.stop()
        finally:
            self.context = None
            self.browser = None
            self._pw = None

    def __enter__(self) -> "App":
        return self.start()

    def __exit__(self, *exc) -> None:
        self.stop()

    # ------------------------------------------------ 访问器

    @property
    def page(self):
        assert self.context is not None, "App 未启动"
        pages = self.context.pages
        return pages[0] if pages else self.context.new_page()

    # ------------------------------------------------ 登录态

    def save_session(self, quiet: bool = False) -> bool:
        """把当前登录态落盘，下次免登录。"""
        from . import login as L

        return L.save_session(self, quiet=quiet)

    def has_session(self) -> bool:
        """是否已保存过登录态。"""
        from . import session as S

        return S.exists()

    def session_info(self) -> dict:
        """登录态摘要，给 UI 用。"""
        from . import session as S

        return S.describe()

    def clear_session(self) -> None:
        """清除登录态（登出）。"""
        from . import session as S

        S.clear()

    # ---- 便捷方法（任务里可直接 app.goto / app.sleep / app.shot）----

    def goto(self, url: str, wait: str = "domcontentloaded") -> None:
        """打开网址。"""
        print(f"[goto] {url}")
        self.page.goto(url, wait_until=wait)

    def sleep(self, sec: float) -> None:
        """等待若干秒。"""
        import time

        time.sleep(sec)

    def shot(self, name: str = "shot", full: bool = True):
        """截图到 artifacts/screenshots/，返回路径。"""
        from datetime import datetime

        p = C.SHOTS / f"{name}-{datetime.now():%Y%m%d-%H%M%S}.png"
        self.page.screenshot(path=str(p), full_page=full)
        print(f"[shot] {p}")
        return p

    # ------------------------------------------------ 任务

    def run_task(self, name: str) -> bool:
        from .tasks import execute_task

        print(f"\n{'=' * 50}\n开始任务：{name}\n{'=' * 50}")
        ok = execute_task(name, self)
        return ok

    def list_tasks(self) -> list[str]:
        from .tasks import list_task_names

        return list_task_names()

    def run_platform(self, name: str) -> bool:
        from .platforms import get_platform

        plat = get_platform(name)
        if plat is None:
            print(f"未找到平台：{name}")
            return False
        return bool(plat.run(self))

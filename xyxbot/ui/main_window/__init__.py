"""主窗口：把各页面 Mixin 与窗口骨架装配起来（已按职责拆分）。

主界面：赵氏集团 · 星月创作台。

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

from xyxbot.ui.main_window.window import WindowMixin
from xyxbot.ui.main_window.scroll import ScrollMixin
from xyxbot.ui.main_window.chrome import ChromeMixin
from xyxbot.ui.main_window.nav import NavMixin
from xyxbot.ui.main_window.runtime import RuntimeMixin
from xyxbot.ui.main_window.nav_item import NavItem
import re
import tkinter as tk
from typing import Callable, Optional
from xyxbot.ui.browser_session import BrowserSession
from xyxbot.ui.defaults import (APP_NAME, COMPANY, DEFAULT_PAGE, EXTRA_PAGES,
                       NAV_ITEMS, PAGE_ALIASES, VERSION)
from xyxbot.ui.pages import (AboutPage, AccountPage, AiFlowMixin, BooksPage,
                    ChaptersMixin, ConfigIOMixin, MorePage, OverviewPage,
                    RunMixin, SettingsPage, SetupMixin, TasksPage)
from xyxbot.ui.theme import (COLOR, F, BrandButton, CheckBox, GradientBar, LogView,
                    StatusBar, bind_configure, bind_wheel, bind_wheel_all,
                    round_rect, unbind_wheel_all, wheel_units)
from xyxbot.ui.pages import (AboutPage, AccountPage, AiFlowMixin, BooksPage,
                    ChaptersMixin, ConfigIOMixin, MorePage, OverviewPage,
                    RunMixin, SettingsPage, SetupMixin, TasksPage)
import tkinter as tk
from xyxbot.ui.pages import (AboutPage, AccountPage, AiFlowMixin, BooksPage,
                    ChaptersMixin, ConfigIOMixin, MorePage, OverviewPage,
                    RunMixin, SettingsPage, SetupMixin, TasksPage)
import tkinter as tk

__all__ = ["WindowMixin", "ScrollMixin", "ChromeMixin", "NavMixin", "RuntimeMixin", "NavItem", "MainWindow"]


class MainWindow(WindowMixin, ScrollMixin, ChromeMixin, NavMixin, RuntimeMixin, AboutPage, AccountPage, AiFlowMixin, BooksPage, ChaptersMixin, ConfigIOMixin, MorePage, OverviewPage, RunMixin, SettingsPage, SetupMixin, TasksPage, tk.Toplevel):
    """主窗口。"""

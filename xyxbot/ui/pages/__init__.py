"""GUI 页面模块（架构改良阶段二 + 2026-10-04 界面重设计）。

把原本 3200+ 行的 `ui/main_window.py` 按「一页一模块」拆开。

设计：每个页面/功能块是一个 **mixin**，由 `MainWindow` 多重继承。
这样页面方法继续以 `self` 访问窗口的控件字段与共享方法，
**原有调用点零改动**，也可以一页一页平滑迁移。

模块一览
--------
======================================  ==========================================
模块                                     职责
======================================  ==========================================
``run``         RunMixin                 ★「跑章」页 —— 唯一主流程（默认页）
``setup``       SetupMixin               「准备」页：登录态 + 运行环境（组合下面两个）
``more``        MorePage                 「更多」页：旧页面的入口清单
``about``       AboutPage                「关于本机」页
``overview``    OverviewPage / MetricCard 「概览面板」页 + 指标卡组件
``account``     AccountPage              「星月账号」页 + 流程准备动作
``books``       BooksPage                「打开作品」页 + 同名候选
``tasks``       TasksPage                「任务中心」页
``settings``    SettingsPage             「运行配置」页 + 浏览器检测
``config_io``   ConfigIOMixin            workspace.json 的记住/回填
``chapters``    ChaptersMixin            分章、章节列表、指令模板、工程存取
``ai_flow``     AiFlowMixin              续写 / 审稿 / 一条龙 / 批量跑章
======================================  ==========================================

★ 2026-10-04 变更：
  * 新增 ``run`` / ``setup`` / ``more`` 三页，主导航收敛为 3 项；
  * **删除 ``content``（小说分章页）** —— 它的内容被拆到「跑章」
    （指令模板 / 细纲 / 参数 / 批量）与「准备」（登录 / 环境）；
  * ``chapters.py`` 里那份**不可达的重复 AI 流程代码**（约 610 行）已删除，
    实际生效的一直是 ``ai_flow.py``（MRO 决定），详见该文件的说明。

★ 关于跨模块调用：这些 mixin 组合成同一个类，所以模块之间互相调用
  `self._xxx()` 都能通过 MRO 正常解析，不需要显式依赖注入。
  各模块的 docstring 里标注了它依赖的外部方法，便于日后继续拆分。
"""

from .about import AboutPage
from .account import AccountPage
from .ai_flow import AiFlowMixin
from .books import BooksPage
from .chapters import ChaptersMixin
from .config_io import ConfigIOMixin
from .more import MorePage
from .overview import MetricCard, OverviewPage
from .run import RunMixin
from .settings import SettingsPage
from .setup import SetupMixin
from .tasks import TasksPage

__all__ = [
    "AboutPage",
    "AccountPage",
    "AiFlowMixin",
    "BooksPage",
    "ChaptersMixin",
    "ConfigIOMixin",
    "MetricCard",
    "MorePage",
    "OverviewPage",
    "RunMixin",
    "SettingsPage",
    "SetupMixin",
    "TasksPage",
]

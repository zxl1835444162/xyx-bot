"""主窗口：把各页面 Mixin 与窗口骨架装配起来（已按职责拆分）。

AI 续写 / 审稿 / 一条龙 / 批量跑章（界面侧编排）。

从 ui/main_window.py 拆出的独立模块（架构改良阶段二）。

★ 依赖（由 MRO 解析）：_collect_notes / _save_ws / _get_instruction /
  _set_preview（chapters、config_io）、_ensure_page / _run_guarded（窗口）。
"""

from __future__ import annotations

from xyxbot.ui.pages.ai_flow.shared import AiFlowSharedMixin
from xyxbot.ui.pages.ai_flow.single import AiSingleMixin
from xyxbot.ui.pages.ai_flow.review import AiReviewMixin
from xyxbot.ui.pages.ai_flow.both import AiBothMixin
from xyxbot.ui.pages.ai_flow.batch import AiBatchMixin
from xyxbot.ui.pages.ai_flow.shared import _int_or
from xyxbot.ui.defaults import (
    DEFAULT_MAX_RETRY,
    DEFAULT_MAX_WORDS,
    DEFAULT_MIN_WORDS,
    DEFAULT_REVIEW_ASSOCIATE,
    DEFAULT_REVIEW_CARD,
    DEFAULT_REVIEW_MODEL,
    DEFAULT_REVIEW_TAB,
    DEFAULT_REVIEW_TIMEOUT,
)

__all__ = ["AiFlowSharedMixin", "AiSingleMixin", "AiReviewMixin", "AiBothMixin", "AiBatchMixin", "AiFlowMixin"]


class AiFlowMixin(AiFlowSharedMixin, AiSingleMixin, AiReviewMixin, AiBothMixin, AiBatchMixin, ):
    """AI 流程（界面侧）。
    
    ★ 2026-10-07 整理：四个入口（续写 / 审稿 / 一条龙 / 批量）原本各自把
      "校验作品 → 渲染指令模板 → 读参数 → 起线程 → 打开作品 → 调后端" 写了一遍，
      573 行里大半是重复。现在共用的部分抽成本类的私有步骤方法（见下方 _ai_* ），
      每个入口只剩"这一步和别的入口哪里不一样"。
    """

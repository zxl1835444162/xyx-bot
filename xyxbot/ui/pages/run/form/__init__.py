"""主窗口：把各页面 Mixin 与窗口骨架装配起来（已按职责拆分）。

① ~ ④ 的控件构建（目标 / 范围 / 指令模板 / 细纲来源）。

本文件由 `xyxbot/ui/pages/run.py` 拆分而来（class split），
只搬位置、不改逻辑：方法体、注释、超时值全部原样。
"""

from __future__ import annotations

from xyxbot.ui.pages.run.form.target import RunTargetMixin
from xyxbot.ui.pages.run.form.notes import RunNotesMixin
from xyxbot.ui.pages.run.form.params import RunParamsMixin
from xyxbot.ui.pages.run.form.progress import RunProgressMixin
from xyxbot.ui.defaults import (
    DEFAULT_MAX_RETRY,
    DEFAULT_MAX_WORDS,
    DEFAULT_MIN_WORDS,
    DEFAULT_REVIEW_ASSOCIATE,
    DEFAULT_REVIEW_CARD,
    DEFAULT_REVIEW_MODEL,
    DEFAULT_REVIEW_REQ,
    DEFAULT_REVIEW_SELECT_ALL,
    DEFAULT_REVIEW_TIMEOUT,
    DEFAULT_REVIEW_WAIT,
    DEFAULT_SHORTCUT,
)
from xyxbot.ui.theme import (COLOR, F, BrandButton, Card, CheckBox, Collapsible,
                     DarkEntry, DimLabel, TitleLabel, bind_configure,
                     bind_wheel)
import tkinter as tk

__all__ = ["RunTargetMixin", "RunNotesMixin", "RunParamsMixin", "RunProgressMixin", "RunFormMixin"]


class RunFormMixin(RunTargetMixin, RunNotesMixin, RunParamsMixin, RunProgressMixin, ):
    """① ~ ④ 的控件构建（目标 / 范围 / 指令模板 / 细纲来源）。"""

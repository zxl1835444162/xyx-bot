"""AI 自动化（原 `xyxbot/ai.py`，5378 行，已按职责拆分）。

对外接口完全不变：`from xyxbot import ai as AI` 之后照旧 `AI.xxx(...)`。
内部结构见各子模块；依赖顺序由 AST 拓扑排序保证。
"""

from __future__ import annotations

from xyxbot.ai.selectors import *  # noqa: F401,F403
from xyxbot.ai.elements import *  # noqa: F401,F403
from xyxbot.ai.dialog import *  # noqa: F401,F403
from xyxbot.ai.current import *  # noqa: F401,F403
from xyxbot.ai.model import *  # noqa: F401,F403
from xyxbot.ai.shortcuts import *  # noqa: F401,F403
from xyxbot.ai.relate import *  # noqa: F401,F403
from xyxbot.ai.body import *  # noqa: F401,F403
from xyxbot.ai.generate import *  # noqa: F401,F403
from xyxbot.ai.chapters import *  # noqa: F401,F403
from xyxbot.ai.review import *  # noqa: F401,F403
from xyxbot.ai.flows import *  # noqa: F401,F403

from xyxbot.ai.selectors import __all__ as _all_0
from xyxbot.ai.elements import __all__ as _all_1
from xyxbot.ai.dialog import __all__ as _all_2
from xyxbot.ai.current import __all__ as _all_3
from xyxbot.ai.model import __all__ as _all_4
from xyxbot.ai.shortcuts import __all__ as _all_5
from xyxbot.ai.relate import __all__ as _all_6
from xyxbot.ai.body import __all__ as _all_7
from xyxbot.ai.generate import __all__ as _all_8
from xyxbot.ai.chapters import __all__ as _all_9
from xyxbot.ai.review import __all__ as _all_10
from xyxbot.ai.flows import __all__ as _all_11

__all__ = [
    *_all_0,
    *_all_1,
    *_all_2,
    *_all_3,
    *_all_4,
    *_all_5,
    *_all_6,
    *_all_7,
    *_all_8,
    *_all_9,
    *_all_10,
    *_all_11,
]

# ★ 会被重新赋值的模块级状态（例如 LAST_DECISION）：不能靠上面的 star-import
#   暴露 —— 那只是导入时的副本，子模块里重新赋值之后这里读到的还是旧值。
#   用 PEP 562 的模块级 __getattr__ 转发到归属模块，读到的永远是当前值。
_LIVE_STATE = {"LAST_DECISION": "flows"}


def __getattr__(name: str):
    """惰性转发「活」状态（见 _LIVE_STATE）。"""
    _mod = _LIVE_STATE.get(name)
    if _mod is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib

    return getattr(importlib.import_module(f"xyxbot.ai.{_mod}"), name)

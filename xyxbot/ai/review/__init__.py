"""AI 审稿（面板、读稿、填写要求、等结果、替换正文）。

本文件由 `xyxbot/ai.py` 拆分而来（Phase C1）。拆分时按 AST 依赖做了拓扑排序，
所以每个模块只 import 排在自己前面的模块，不存在循环引用。

---
（上面这段是拆分前原模块的说明，原样保留。）

实现已按职责拆分到本包子模块，依赖顺序由 AST 拓扑排序保证。
"""

from __future__ import annotations

from xyxbot.ai.review.text import *  # noqa: F401,F403
from xyxbot.ai.review.pane import *  # noqa: F401,F403
from xyxbot.ai.review.pick import *  # noqa: F401,F403
from xyxbot.ai.review.gen import *  # noqa: F401,F403
from xyxbot.ai.review.replace import *  # noqa: F401,F403

from xyxbot.ai.review.text import __all__ as _all_0
from xyxbot.ai.review.pane import __all__ as _all_1
from xyxbot.ai.review.pick import __all__ as _all_2
from xyxbot.ai.review.gen import __all__ as _all_3
from xyxbot.ai.review.replace import __all__ as _all_4

__all__ = [
    *_all_0,
    *_all_1,
    *_all_2,
    *_all_3,
    *_all_4,
]

# ★ 兼容转发：老代码/老测试会直接摸 theme.xxx（例如 theme.tk、theme.tkfont、
#   theme._platform_key），这些名字现在住在子模块里。读访问一律转发到
#   第一个拥有它的子模块 —— 拿到的都是**同一个对象**（模块、函数、字典）。
#   注意：**写**（theme.X = ...）不会转发，那只会给包加一个影子属性；
#   要给子模块改状态请直接改子模块（xyxbot.ui.theme.fonts._SYS_FAMILIES）。
_LIVE_STATE = {}
_SUB_MODULES = ["text", "pane", "pick", "gen", "replace"]


def __getattr__(name: str):
    import importlib

    _mod = _LIVE_STATE.get(name)
    if _mod is not None:
        return getattr(importlib.import_module("xyxbot.ai.review." + _mod), name)
    for _m in _SUB_MODULES:
        _sub = importlib.import_module("xyxbot.ai.review." + _m)
        if hasattr(_sub, name):
            return getattr(_sub, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

"""控件类（Card / BrandButton / DarkEntry / LogView …）。

本文件由原巨型模块拆分而来（Phase C2/C1），拆分时按 AST 依赖做了拓扑排序，
每个模块只 import 排在自己前面的模块，不存在循环引用。

---
（上面这段是拆分前原模块的说明，原样保留。）

实现已按职责拆分到本包子模块，依赖顺序由 AST 拓扑排序保证。
"""

from __future__ import annotations

from xyxbot.ui.theme.widgets.atoms import *  # noqa: F401,F403
from xyxbot.ui.theme.widgets.panels import *  # noqa: F401,F403
from xyxbot.ui.theme.widgets.buttons import *  # noqa: F401,F403
from xyxbot.ui.theme.widgets.entries import *  # noqa: F401,F403

from xyxbot.ui.theme.widgets.atoms import __all__ as _all_0
from xyxbot.ui.theme.widgets.panels import __all__ as _all_1
from xyxbot.ui.theme.widgets.buttons import __all__ as _all_2
from xyxbot.ui.theme.widgets.entries import __all__ as _all_3

__all__ = [
    *_all_0,
    *_all_1,
    *_all_2,
    *_all_3,
]

# ★ 兼容转发：老代码/老测试会直接摸 theme.xxx（例如 theme.tk、theme.tkfont、
#   theme._platform_key），这些名字现在住在子模块里。读访问一律转发到
#   第一个拥有它的子模块 —— 拿到的都是**同一个对象**（模块、函数、字典）。
#   注意：**写**（theme.X = ...）不会转发，那只会给包加一个影子属性；
#   要给子模块改状态请直接改子模块（xyxbot.ui.theme.fonts._SYS_FAMILIES）。
_LIVE_STATE = {}
_SUB_MODULES = ["atoms", "panels", "buttons", "entries"]


def __getattr__(name: str):
    import importlib

    _mod = _LIVE_STATE.get(name)
    if _mod is not None:
        return getattr(importlib.import_module("xyxbot.ui.theme.widgets." + _mod), name)
    for _m in _SUB_MODULES:
        _sub = importlib.import_module("xyxbot.ui.theme.widgets." + _m)
        if hasattr(_sub, name):
            return getattr(_sub, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

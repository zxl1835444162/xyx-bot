"""深色主题与自绘组件库。

tkinter 原生 ttk 控件无法做圆角、渐变、阴影，因此这里用 Canvas 自绘一套，
以获得现代质感。所有颜色集中在本文件，改主题只需改 COLOR 字典。

---
（上面这段是拆分前原模块的说明，原样保留。）

实现已按职责拆分到本包子模块，依赖顺序由 AST 拓扑排序保证。
"""

from __future__ import annotations

from xyxbot.ui.theme.palette import *  # noqa: F401,F403
from xyxbot.ui.theme.fonts import *  # noqa: F401,F403
from xyxbot.ui.theme.redraw import *  # noqa: F401,F403
from xyxbot.ui.theme.scroll import *  # noqa: F401,F403
from xyxbot.ui.theme.widgets import *  # noqa: F401,F403

from xyxbot.ui.theme.palette import __all__ as _all_0
from xyxbot.ui.theme.fonts import __all__ as _all_1
from xyxbot.ui.theme.redraw import __all__ as _all_2
from xyxbot.ui.theme.scroll import __all__ as _all_3
from xyxbot.ui.theme.widgets import __all__ as _all_4

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
_LIVE_STATE = {"_SYS_FAMILIES": "fonts"}
_SUB_MODULES = ["palette", "fonts", "redraw", "scroll", "widgets"]


def __getattr__(name: str):
    import importlib

    _mod = _LIVE_STATE.get(name)
    if _mod is not None:
        return getattr(importlib.import_module("xyxbot.ui.theme." + _mod), name)
    for _m in _SUB_MODULES:
        _sub = importlib.import_module("xyxbot.ui.theme." + _m)
        if hasattr(_sub, name):
            return getattr(_sub, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

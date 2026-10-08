"""作品页操作：进入作品列表、打开已有作品、新建作品。

★ 关键坑（实测于 2026-10-03）
    作品页上「新建作品」**不是一个唯一的文字**。实际存在：
        - 入口卡：一个虚线框大加号，class 含 `create-card`   ← 这才是要点的
        - 已有作品 A：名字就叫「新建作品」（用户建的作品恰好这个名字）
        - 已有作品 B：名字叫「新建作品1」

    所以：
        ❌ `text=新建作品`  → 命中 4 个，会点到别人的作品
        ✅ `.create-card`   → 唯一命中，安全

★ 第二个坑：作品名**会重复**
    实测出现过 3 部同名「自动化测试-勿动」。所以「打开某个作品」不能只靠名字，
    真正的唯一标识是卡片内的 `#/chapters/<数字ID>` 链接。
    `list_books()` 会把 ID 一起读出来，`open_book()` 做模糊匹配 + 消歧。

    本模块统一用 `click_strict` + `.create-card`，从机制上避免点错。

---
（上面这段是拆分前原模块的说明，原样保留。）

实现已按职责拆分到本包子模块，依赖顺序由 AST 拓扑排序保证。
"""

from __future__ import annotations

from xyxbot.books.editor import *  # noqa: F401,F403
from xyxbot.books.modal import *  # noqa: F401,F403
from xyxbot.books.nav import *  # noqa: F401,F403
from xyxbot.books.list import *  # noqa: F401,F403
from xyxbot.books.open_ import *  # noqa: F401,F403
from xyxbot.books.create import *  # noqa: F401,F403

from xyxbot.books.editor import __all__ as _all_0
from xyxbot.books.modal import __all__ as _all_1
from xyxbot.books.nav import __all__ as _all_2
from xyxbot.books.list import __all__ as _all_3
from xyxbot.books.open_ import __all__ as _all_4
from xyxbot.books.create import __all__ as _all_5

__all__ = [
    *_all_0,
    *_all_1,
    *_all_2,
    *_all_3,
    *_all_4,
    *_all_5,
]

# ★ 兼容转发：老代码/老测试会直接摸 theme.xxx（例如 theme.tk、theme.tkfont、
#   theme._platform_key），这些名字现在住在子模块里。读访问一律转发到
#   第一个拥有它的子模块 —— 拿到的都是**同一个对象**（模块、函数、字典）。
#   注意：**写**（theme.X = ...）不会转发，那只会给包加一个影子属性；
#   要给子模块改状态请直接改子模块（xyxbot.ui.theme.fonts._SYS_FAMILIES）。
_LIVE_STATE = {}
_SUB_MODULES = ["editor", "modal", "nav", "list", "open_", "create"]


def __getattr__(name: str):
    import importlib

    _mod = _LIVE_STATE.get(name)
    if _mod is not None:
        return getattr(importlib.import_module("xyxbot.books." + _mod), name)
    for _m in _SUB_MODULES:
        _sub = importlib.import_module("xyxbot.books." + _m)
        if hasattr(_sub, name):
            return getattr(_sub, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

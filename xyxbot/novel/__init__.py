"""小说分章 + 短代号模板（#1 / #2 / ...）。

把一部小说的 .txt 全文拆成「一章一个短代号」，供 UI 里的输入框填写细纲。

★ 核心设计（用户需求）：
    每一章 = 一个**短代号**，形如 `#1` `#2` `#3`（代表你在输入框里填的细纲）

    然后你可以写一段**指令模板**，把代号嵌进自然语言里：

        根据 #1 的细纲，续写下一段正文，保持爽文节奏。前文脉络参考 #2。

    程序会把 `#1` 替换成第 1 章输入框里的细纲，`#2` 同理，得到最终文本。

兼容写法（都认）：
    #1    #1     [1]     第1章      {{第1章}}

「关联章节」（最近10章）不在这里处理 —— 那是站点弹窗里的选项，
由 ai.py 在浏览器里点。

用法：
    from xyxbot.novel import NovelProject

    proj = NovelProject.load("C:/.../开局被绿.txt")
    proj.chapters               # [Chapter(no=1, code="#1", title=..., body=...)]
    proj.tokens()               # ["#1", "#2", ...]
    proj.set_note(1, "陆晨发现被绿…")
    proj.render_template("根据 #1 的细纲续写正文，参考 #2")
    # → "根据 陆晨发现被绿… 的细纲续写正文，参考 …"
    proj.save("proj.json") / NovelProject.open("proj.json")

---
（上面这段是拆分前原模块的说明，原样保留。）

实现已按职责拆分到本包子模块，依赖顺序由 AST 拓扑排序保证。
"""

from __future__ import annotations

from xyxbot.novel.patterns import *  # noqa: F401,F403
from xyxbot.novel.chapter import *  # noqa: F401,F403
from xyxbot.novel.split import *  # noqa: F401,F403
from xyxbot.novel.project import *  # noqa: F401,F403
from xyxbot.novel.cli import *  # noqa: F401,F403

from xyxbot.novel.patterns import __all__ as _all_0
from xyxbot.novel.chapter import __all__ as _all_1
from xyxbot.novel.split import __all__ as _all_2
from xyxbot.novel.project import __all__ as _all_3
from xyxbot.novel.cli import __all__ as _all_4

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
_SUB_MODULES = ["patterns", "chapter", "split", "project", "cli"]


def __getattr__(name: str):
    import importlib

    _mod = _LIVE_STATE.get(name)
    if _mod is not None:
        return getattr(importlib.import_module("xyxbot.novel." + _mod), name)
    for _m in _SUB_MODULES:
        _sub = importlib.import_module("xyxbot.novel." + _m)
        if hasattr(_sub, name):
            return getattr(_sub, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

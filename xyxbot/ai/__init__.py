"""星月写作 —— AI 续写正文自动化。

流程（每一步都实测过选择器）：

    1. 进编辑器页（用 books.open_book）
    2. 点顶部「AI续写正文」按钮
    3. 在弹窗里：
       a. 选「快捷选项」（提示词）—— ★ 用文字定位，见 pick_shortcut()
       b. 选模型 → 打开模型面板 → 点「细腻版」→ 点「使用此模型」
       c. 填「后续剧情」= 前缀 + 内容 + 后缀
       d. 关联章节 → 展开 → 点箭头 → 选「最近10章」
       e. 点「开始 AI 续写」

★ 实测于 2026-10-03。关键选择器：

| 元素 | 选择器 |
|---|---|
| AI续写正文按钮 | `button:has-text('AI续写正文')` |
| 后续剧情输入框 | `.n-modal textarea[placeholder*='后续剧情走向']` |
| 模型选择器 | `.n-modal .n-base-selection` （显示当前版本名，如「奇想版」） |
| 细腻版（分类） | `span.flex-1.truncate:has-text('细腻版')` |
| 联想能力按钮 | `button:has-text('联想能力')` |
| 使用此模型 | `button:has-text('使用此模型')` |
| 关联章节头 | `button:has-text('关联章节')` |
| 章节数下拉箭头 | `button.h-9.w-7`（在「最近5章」右边） |
| 开始AI续写 | `button:has-text('开始 AI 续写')` |

★ 「快捷选项」（续写要求那一行）—— 实测反直觉，单独说：

| 元素 | 选择器 |
|---|---|
| 那一行（Naive n-select） | `.n-form-item:has-text('续写要求') .n-base-selection` |
| 弹出的全屏面板 | `.shortcut-picker-modal` |
| 面板里的提示词行 | `.shortcut-picker-modal .prompt-row` |
| 行内标题文字 | `.row-title` |
| 面板搜索框 | `.shortcut-picker-modal input[placeholder*='搜索']` |

**点那一行不弹下拉菜单，而是弹一个全屏 modal**；
面板里点中某一行 `.prompt-row` → 面板自动关 → 那一行显示改成该提示词名。
**定位方式：用文字**（`.prompt-row:has-text('关键词')`），
不记第几行 —— 因为列表顺序 / 收藏数 / 运营推荐都会变。

---
（上面这段是拆分前 `xyxbot/ai.py` 的模块说明，原样保留。）

实现已按职责拆分到本包的 12 个子模块，依赖顺序由 AST 拓扑排序保证：
selectors → elements → dialog → current → model → shortcuts → relate
          → body → generate → chapters → review → flows
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

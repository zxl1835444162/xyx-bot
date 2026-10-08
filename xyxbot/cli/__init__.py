"""命令行入口。

架构参考 novel-publisher-mac：
    xyxbot/platforms/   平台适配器注册表（一个站点一个类）
    xyxbot/tasks/       任务注册表（一个流程一个函数）
    xyxbot/app.py       App 主类，把浏览器 / 平台 / 任务串起来

命令既可以用 `python main.py <命令>`，也可以用 `python -m xyxbot <命令>`：
    python main.py login        登录一次，保存登录态（之后免登录）
    python main.py session      查看登录态详情
    python main.py check        检查登录态是否有效
    python main.py diag         诊断登录态（排查"为什么没记录到 cookie"）
    python main.py recon        侦察页面，打印可见元素（写选择器用）
    python main.py logout       清除登录态
    python main.py books        列出作品页上的所有作品（带 ID）
    python main.py open <名字>  打开指定作品（同名可加 --index N）
    python main.py ai <作品名>  AI 续写正文（细腻版 + 联想正常 + 最近10章）
    python main.py review <作品名>  AI 审稿（智慧版-6A + 联想正常 + 指定审稿要求）
    python main.py tasks        列出所有已注册任务
    python main.py platforms    列出所有已注册平台
    python main.py run <任务名>  执行指定任务
    python main.py studio       快捷：登录并进创作台
    python main.py browsers     检测本机可用浏览器

---
（上面这段是拆分前原模块的说明，原样保留。）

实现已按职责拆分到本包子模块，依赖顺序由 AST 拓扑排序保证。
"""

from __future__ import annotations

from xyxbot.cli.session import *  # noqa: F401,F403
from xyxbot.cli.site import *  # noqa: F401,F403
from xyxbot.cli.book import *  # noqa: F401,F403
from xyxbot.cli.ai import *  # noqa: F401,F403
from xyxbot.cli.review_ import *  # noqa: F401,F403
from xyxbot.cli.entry import *  # noqa: F401,F403

from xyxbot.cli.session import __all__ as _all_0
from xyxbot.cli.site import __all__ as _all_1
from xyxbot.cli.book import __all__ as _all_2
from xyxbot.cli.ai import __all__ as _all_3
from xyxbot.cli.review_ import __all__ as _all_4
from xyxbot.cli.entry import __all__ as _all_5

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
_SUB_MODULES = ["session", "site", "book", "ai", "review_", "entry"]


def __getattr__(name: str):
    import importlib

    _mod = _LIVE_STATE.get(name)
    if _mod is not None:
        return getattr(importlib.import_module("xyxbot.cli." + _mod), name)
    for _m in _SUB_MODULES:
        _sub = importlib.import_module("xyxbot.cli." + _m)
        if hasattr(_sub, name):
            return getattr(_sub, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

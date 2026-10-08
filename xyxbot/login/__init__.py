"""登录态管理（基于实测的星月写作登录页结构）。

登录页有两个 Tab：
    1.「微信登录 / 注册」—— 默认显示，扫码登录
    2.「账号密码」—— 需点 Tab 才渲染输入框，可全自动登录

因此提供两条路：
    auto_login(page, user, pwd)  -> 有账号密码时全自动
    manual_login(page)           -> 没账号密码时，人工扫码/输入
    ensure_login(app)            -> 先查登录态，失效才走上面流程

★ 登录态复用（核心）
    只要登录成功一次，就立刻把 cookie + localStorage 导出到
    artifacts/storage/state.json。之后每次启动浏览器都注入这份 state，
    等同于「你早就登录过了」——**不用再扫码/输密码**。
    这套逻辑在 src/session.py，本模块负责在正确的时机调用它。

    调用关系：
        ensure_login(app)
          ├─ 注入已有 state 打开站点
          ├─ 已登录？→ 直接用，结束
          ├─ 有账号密码？→ auto_login() → 成功后 save_session()
          └─ 否则 → manual_login()        → 成功后 save_session()

---
（上面这段是拆分前原模块的说明，原样保留。）

实现已按职责拆分到本包子模块，依赖顺序由 AST 拓扑排序保证。
"""

from __future__ import annotations

from xyxbot.login.state import *  # noqa: F401,F403
from xyxbot.login.flow import *  # noqa: F401,F403
from xyxbot.login.prepare import *  # noqa: F401,F403

from xyxbot.login.state import __all__ as _all_0
from xyxbot.login.flow import __all__ as _all_1
from xyxbot.login.prepare import __all__ as _all_2

__all__ = [
    *_all_0,
    *_all_1,
    *_all_2,
]

# ★ 兼容转发：老代码/老测试会直接摸 theme.xxx（例如 theme.tk、theme.tkfont、
#   theme._platform_key），这些名字现在住在子模块里。读访问一律转发到
#   第一个拥有它的子模块 —— 拿到的都是**同一个对象**（模块、函数、字典）。
#   注意：**写**（theme.X = ...）不会转发，那只会给包加一个影子属性；
#   要给子模块改状态请直接改子模块（xyxbot.ui.theme.fonts._SYS_FAMILIES）。
_LIVE_STATE = {}
_SUB_MODULES = ["state", "flow", "prepare"]


def __getattr__(name: str):
    import importlib

    _mod = _LIVE_STATE.get(name)
    if _mod is not None:
        return getattr(importlib.import_module("xyxbot.login." + _mod), name)
    for _m in _SUB_MODULES:
        _sub = importlib.import_module("xyxbot.login." + _m)
        if hasattr(_sub, name):
            return getattr(_sub, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

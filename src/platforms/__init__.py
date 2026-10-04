"""平台基类与注册表（移植自 novel_publisher/platforms.py 设计）。

参考项目用它管理「番茄/起点/七猫...」多个发布平台；
这里用它管理「星月写作」以及你以后要接的其它站点。

用法：
    @register_platform
    class XingyuePlatform(BasePlatform):
        name = "星月写作"
        url = "https://xingyuexiezuo.com/"

        def run(self, app) -> bool:
            ...
"""

from __future__ import annotations

from typing import Callable, Dict, List


class BasePlatform:
    """所有平台适配器的基类。"""

    name: str = ""           # 界面显示名
    url: str = ""            # 站点入口
    login_hint: str = ""     # 登录方式说明

    def run(self, app) -> bool:
        """执行该平台的自动化流程。子类必须实现。"""
        raise NotImplementedError(f"{type(self).__name__} 未实现 run()")

    def __repr__(self) -> str:
        return f"<Platform {self.name}>"


# ------------------------------------------------------------------ 注册表

_PLATFORMS: Dict[str, BasePlatform] = {}


def register_platform(cls: type[BasePlatform]) -> type[BasePlatform]:
    """类装饰器：注册平台。必须设置 name。"""
    if not cls.name:
        raise ValueError(f"{cls.__name__} 必须定义 name")
    inst = cls()
    _PLATFORMS[cls.name] = inst
    return cls


def get_platform(name: str) -> BasePlatform | None:
    return _PLATFORMS.get(name)


def list_platform_names() -> List[str]:
    return list(_PLATFORMS.keys())


def all_platforms() -> Dict[str, BasePlatform]:
    return dict(_PLATFORMS)


# 导入适配器模块以触发注册（放在文件末尾避免循环导入）
from . import adapters  # noqa: E402,F401

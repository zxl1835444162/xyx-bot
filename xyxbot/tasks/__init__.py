"""任务注册表与调度（移植自 novel_publisher/tasks.py）。

- 注册表本体在本文件
- `tasks/adapters.py` 把具体任务函数注册进来

用法：
    @register_task("自动发布", threaded=True)
    def auto_publish(app):
        ...
"""

from __future__ import annotations

import threading
from typing import Callable, Dict, Optional

_TASKS: Dict[str, tuple] = {}


def register_task(name: str, threaded: Optional[bool] = None) -> Callable:
    """装饰器：注册任务。

    Args:
        name: 任务名称（与界面下拉框对应）
        threaded: True 在子线程执行，False 主线程直接调用，None 由调用方决定
    """
    def decorator(func: Callable):
        _TASKS[name] = (func, threaded)
        return func
    return decorator


def get_task(name: str):
    """获取 (执行函数, 是否子线程)。"""
    return _TASKS.get(name)


def list_task_names():
    """返回所有已注册的任务名。"""
    return list(_TASKS.keys())


def execute_task(name: str, app) -> bool:
    """执行指定任务。返回 True 表示已启动。"""
    task = get_task(name)
    if task is None:
        print(f"未找到任务: {name}")
        return False
    func, threaded = task
    if threaded:
        threading.Thread(target=func, args=(app,), daemon=True).start()
    else:
        func(app)
    return True


from . import adapters  # noqa: E402,F401  触发任务注册

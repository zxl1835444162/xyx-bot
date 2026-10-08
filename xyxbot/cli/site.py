"""站点与环境类命令：recon / browsers / platforms / tasks / run / studio。

本文件由原巨型模块拆分而来（Phase C2/C1），拆分时按 AST 依赖做了拓扑排序，
每个模块只 import 排在自己前面的模块，不存在循环引用。
"""

from __future__ import annotations


import sys

__all__ = ["cmd_browsers", "cmd_platforms", "cmd_recon", "cmd_run", "cmd_studio", "cmd_tasks"]


def cmd_recon() -> None:
    from xyxbot.app import App

    with App(headless=False) as app:
        app.run_task("侦察页面")



def cmd_tasks() -> None:
    from xyxbot.tasks import list_task_names

    print("已注册任务：")
    for n in list_task_names():
        print("  •", n)



def cmd_platforms() -> None:
    from xyxbot.platforms import all_platforms

    print("已注册平台：")
    for name, p in all_platforms().items():
        print(f"  • {name}  {p.url}")
        if p.login_hint:
            print(f"      登录方式: {p.login_hint}")



def cmd_run() -> None:
    if len(sys.argv) < 3:
        print("用法: python main.py run <任务名>")
        print("可用任务见: python main.py tasks")
        sys.exit(1)
    from xyxbot.app import App

    with App(headless=False) as app:
        ok = app.run_task(sys.argv[2])
    sys.exit(0 if ok else 1)



def cmd_studio() -> None:
    from xyxbot.app import App

    with App(headless=False) as app:
        app.run_platform("星月写作")



def cmd_browsers() -> None:
    from xyxbot.browser_detector import test_browser_detection

    test_browser_detection()

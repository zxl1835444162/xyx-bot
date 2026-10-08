"""登录态与自检类命令：login / session / check / logout / diag / selftest。

本文件由原巨型模块拆分而来（Phase C2/C1），拆分时按 AST 依赖做了拓扑排序，
每个模块只 import 排在自己前面的模块，不存在循环引用。
"""

from __future__ import annotations


import sys

__all__ = ["cmd_check", "cmd_diag", "cmd_login", "cmd_logout", "cmd_selftest", "cmd_session"]


# ---------------------------------------------------------------- 命令实现

def cmd_login() -> None:
    from xyxbot.app import App
    from xyxbot.login import ensure_login

    with App(headless=False) as app:
        ok = ensure_login(app)
    print("\n登录态已保存，下次启动无需再次登录 ✓" if ok else "\n未取得登录态 ✗")
    sys.exit(0 if ok else 1)



def cmd_session() -> None:
    """查看登录态详情。"""
    from xyxbot import session as S

    if not S.exists():
        print("尚未保存登录态。执行 `python main.py login` 登录一次即可。")
        sys.exit(1)

    info = S.describe()
    print("登录态详情")
    print("-" * 40)
    print(f"  保存时间 : {info['saved_at']}")
    print(f"  已过时长 : {S.age_text()}")
    print(f"  Cookie   : {info['cookies']} 条")
    print(f"  文件大小 : {info['size']}")
    print(f"  文件路径 : {info['path']}")
    if info.get("account"):
        print(f"  登录账号 : {info['account']}")



def cmd_check() -> None:
    from xyxbot.app import App
    from xyxbot import login as L

    with App(headless=False) as app:
        ok = L.verify_session(app)
    sys.exit(0 if ok else 1)



def cmd_logout() -> None:
    from xyxbot import session as S

    S.clear()
    print("[login] 本地登录态已清除，下次使用需重新登录")



def cmd_selftest() -> None:
    """环境自检：检查 tkinter / 数据目录 / Playwright / 浏览器内核，
    并且**真的把界面构造一遍**（打包版排障和 CI 验证都靠它）。

    `--no-ui`     跳过界面冒烟，只做环境检查
    `--window`    强制做「窗口真的显示出来了吗」的探测（会显示窗口）
    `--no-window` 强制不做（CI 环境自动关闭）
    """
    from xyxbot.selftest import run_selftest

    wp = None
    if "--window" in sys.argv:
        wp = True
    elif "--no-window" in sys.argv:
        wp = False
    sys.exit(run_selftest(smoke_ui="--no-ui" not in sys.argv, window_probe=wp))



def cmd_diag() -> None:
    """诊断登录态：排查「为什么没记录到 cookie」。"""
    import runpy

    from xyxbot import config as C

    # ★ 打包（.app / .exe）之后，开发期脚本没被打进去，直接 run_path 会报
    #   FileNotFoundError。这里先说清楚。
    script = C.ROOT / "tools" / "diag" / "diag_login.py"
    if not script.exists():
        print("diag 是开发期脚本（tools/diag/diag_login.py），打包版里没有它。")
        print("请改用：python main.py session   查看登录态详情")
        sys.exit(2)

    sys.argv = ["diag_login.py"]
    runpy.run_path(str(script), run_name="__main__")

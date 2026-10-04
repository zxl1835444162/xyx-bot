"""GUI 启动入口：登录 -> 主界面。

用法：
    python run_gui.py                 # 启动图形界面
    python run_gui.py --selftest      # 只做环境自检，不打开窗口
                                      # （排障 / CI 验证打包产物用）
"""

from __future__ import annotations

import sys
import traceback
from pathlib import Path

# 确保能 import src / ui
# ★ 打包（PyInstaller）之后 __file__ 指向 .app 内部，仍然可用；
#   而 sys.path 里已经有打包器准备好的路径，这里只是双保险。
try:
    ROOT = Path(__file__).resolve().parent
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
except Exception:
    ROOT = Path.cwd()

# ★ 输出重定向时避免 GBK 编码崩溃（详见 src/console.py）
try:
    from src.console import enable_utf8

    enable_utf8()
except Exception:
    pass


def _show_fatal(err: str) -> None:
    """启动失败时弹窗提示，而不是无声闪退。"""
    print(err, file=sys.stderr)
    try:
        import tkinter as tk
        from tkinter import messagebox

        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("启动失败", err[:2000])
        root.destroy()
    except Exception:
        try:
            input("启动失败，按回车退出...")
        except Exception:
            pass


def launch_main(username: str) -> None:
    """启动主界面；点退出登录则回到登录窗口。"""
    from ui.login_window import LoginWindow
    from ui.main_window import MainWindow

    def back_to_login() -> None:
        LoginWindow(on_success=launch_main).mainloop()

    MainWindow(username=username, on_logout=back_to_login).mainloop()


def main() -> None:
    # ★ --selftest：不创建任何窗口，只检查环境（CI 与用户排障都用它）
    if "--selftest" in sys.argv or "-selftest" in sys.argv:
        try:
            from src.selftest import run_selftest

            sys.exit(run_selftest())
        except Exception:
            print("自检本身失败了：\n" + traceback.format_exc())
            sys.exit(2)

    try:
        from ui.shot import make_dpi_aware
        from ui.login_window import LoginWindow

        make_dpi_aware()
    except Exception:
        _show_fatal("初始化失败：\n\n" + traceback.format_exc())
        sys.exit(1)

    try:
        LoginWindow(on_success=launch_main).mainloop()
    except Exception:
        _show_fatal("运行失败：\n\n" + traceback.format_exc())
        sys.exit(1)


if __name__ == "__main__":
    main()

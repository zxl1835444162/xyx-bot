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


def _dialog_allowed() -> bool:
    """要不要弹窗。设了 `XYX_NO_DIALOG=1` 就返回 False。

    ★ CI / 自动化场景必须关掉：`messagebox` 是**模态**的，在没人点的
      runner 上会一直挂着把 job 卡死。
      （这里原来写反了 —— `not in ("", "0")` 变成了"设了才允许"，
        被 tests/test_login_flow.py 抓出来。）
    """
    import os

    return os.getenv("XYX_NO_DIALOG", "") in ("", "0")


def _show_fatal(err: str) -> None:
    """启动失败时弹窗提示，而不是无声闪退。"""
    print(err, file=sys.stderr)
    _log_fatal(err)
    if not _dialog_allowed():
        return
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


def _log_fatal(err: str) -> None:
    """把致命错误同时写一份到数据目录，方便事后排查。

    ★★ 为什么必须写文件（2026-10-04 用户实测：macOS 上"输完密码进不去"）
      打包成 .app 之后 `console=False`，**stderr 是断的** ——
      Tk 的 `report_callback_exception` 默认只把堆栈打印到 stderr，
      于是异常在用户那儿表现为"点了没反应、什么都不显示"，
      完全查不出原因。写文件才有据可查。
    """
    try:
        from src import config as C

        p = C.LOGS / "fatal.log"
        with open(p, "a", encoding="utf-8") as f:
            from datetime import datetime

            f.write(f"\n===== {datetime.now():%Y-%m-%d %H:%M:%S} =====\n")
            f.write(err)
            if not err.endswith("\n"):
                f.write("\n")
        print(f"[fatal] 已写入 {p}", file=sys.stderr)
    except Exception:
        pass


def _install_error_handler() -> None:
    """接管 Tk 的回调异常，别再静默吞掉。

    ★★ 这是"输完授权码进不去主界面"的**根因可见化**（2026-10-04）：
      登录窗口的 `_enter()` 是这么走的：

          self.after(420, lambda: self._enter(user))   # ← 在 Tk 回调里
          def _enter(self, user):
              self.destroy()            # 登录窗先没了
              self._on_success(user)    # ← 这里抛异常 → 主窗根本没建起来

      回调里的异常会被 Tk 交给 `report_callback_exception`，而它的默认实现
      只是 `traceback.print_exception` 到 **stderr** —— 打包后的 .app 里
      stderr 没有去处。结果就是：登录窗消失、主界面不出现、**没有任何提示**。

      这里改成：① 弹窗把堆栈显示出来；② 同时写入 logs/fatal.log。
    """
    import tkinter as tk

    def _hook(self, exc, val, tb):
        text = "".join(traceback.format_exception(exc, val, tb))
        print("Exception in Tkinter callback\n" + text, file=sys.stderr)
        _log_fatal("Tk 回调异常：\n" + text)
        if not _dialog_allowed():
            return
        try:
            from tkinter import messagebox

            messagebox.showerror(
                "界面出错了",
                "界面操作时发生异常，请把下面这段发给开发者：\n\n"
                + text[-1800:])
        except Exception:
            pass

    tk.Tk.report_callback_exception = _hook


def launch_main(username: str) -> None:
    """启动主界面；点退出登录则回到登录窗口。

    ★ 这里包一层 try/except：即使没有走 Tk 回调（比如从命令行直接调），
      也能把失败原因弹出来，而不是静默什么都不发生。
    """
    from ui.login_window import LoginWindow
    from ui.main_window import MainWindow

    def back_to_login() -> None:
        LoginWindow(on_success=launch_main).mainloop()

    try:
        MainWindow(username=username, on_logout=back_to_login).mainloop()
    except Exception:
        _show_fatal("主界面启动失败：\n\n" + traceback.format_exc())
        raise


def main() -> None:
    # ★ 先装好回调异常处理器，再创建任何窗口
    try:
        _install_error_handler()
    except Exception:
        pass

    # ★ --selftest：不创建主界面，只检查环境（CI 与用户排障都用它）
    #   --selftest --ui：另外**真的把主窗口构造一遍**（不进事件循环），
    #   这是唯一能验证"打包产物里的界面能不能起来"的办法。
    if "--selftest" in sys.argv or "-selftest" in sys.argv:
        # 默认**连界面一起冒烟**（这才是能抓到"进不去主界面"的那一步）；
        # 用 --no-ui 可以只做环境检查。
        want_ui = "--no-ui" not in sys.argv
        # 窗口显示探测：用户本机默认开，CI 自动关（在 macOS runner 上会卡死）
        wp = None
        if "--window" in sys.argv:
            wp = True
        elif "--no-window" in sys.argv:
            wp = False
        try:
            from src.selftest import run_selftest

            sys.exit(run_selftest(smoke_ui=want_ui, window_probe=wp))
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

"""GUI 启动入口：登录 -> 主界面。

用法：
    python run_gui.py                 # 启动图形界面
    python run_gui.py --selftest      # 只做环境自检，不打开窗口
                                      # （排障 / CI 验证打包产物用）
"""

from __future__ import annotations

import os
import sys
import threading
import time
import tkinter as tk
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

        # ★ 复用已有的 root。macOS 上**多建一个 tk.Tk()** 会让后面的窗口
        #   收不到事件（本项目真正的 bug），所以这里绝不无脑新建。
        root = getattr(tk, "_default_root", None)
        own_root = root is None
        if root is None:
            root = tk.Tk()
        root.withdraw()
        # ★ 尽力把弹窗弄到最前面：macOS 上新建的窗口不一定抢到焦点，
        #   用户可能根本看不到这个错误框（"点了没反应"的另一种成因）。
        try:
            root.lift()
            root.attributes("-topmost", True)
            root.focus_force()
        except Exception:
            pass
        messagebox.showerror("启动失败",
                            err[:2000] + "\n\n（完整报告已写到桌面："
                            "XYXBot-诊断.txt）")
        if own_root:
            root.destroy()
    except Exception as _e:
        # ★ 连弹窗都失败了 —— 这件事本身也要留痕，否则就成了"什么都没发生"
        _log_fatal(f"[弹窗失败] {type(_e).__name__}: {_e}\n"
                   "（上面的报告就是原因；弹窗失败通常是 macOS 权限/焦点问题）")
        try:
            input("启动失败，按回车退出...")
        except Exception:
            pass


def _log_fatal(err: str) -> None:
    """把致命错误/卡死报告写到**好找的地方**。

    ★★ 为什么必须写文件（2026-10-04 用户实测：macOS 上「输完密码进不去」）
      打包成 .app 之后 `console=False`，**stderr 是断的** ——
      Tk 的 `report_callback_exception` 默认只把堆栈打印到 stderr，
      于是异常在用户那儿表现为"点了没反应、什么都不显示"，
      完全查不出原因。写文件才有据可查。

    ★ 除了数据目录，还额外写一份到**桌面**：让用户一眼就能找到、直接发我。
      （数据目录藏在 `~/Library/Application Support/...` 里，很多人找不到。）
    """
    stamp = ""
    try:
        from src import _buildinfo as B

        stamp = B.describe() + "\n"
    except Exception:
        pass
    text = stamp + err

    targets = []
    try:
        from src import config as C

        targets.append(C.LOGS / "fatal.log")
    except Exception:
        pass
    try:
        targets.append(Path.home() / "Desktop" / "XYXBot-诊断.txt")
    except Exception:
        pass

    for p in targets:
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            with open(p, "a", encoding="utf-8") as f:
                from datetime import datetime

                f.write(f"\n===== {datetime.now():%Y-%m-%d %H:%M:%S} =====\n")
                f.write(text)
                if not text.endswith("\n"):
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


def run_app() -> int:
    """★★ 单 root + 可切换窗口：登录 ⇄ 主界面。

    ★★★ 为什么必须是"单 root"（2026-10-04，真机复现，这是真正的根因）
    =====================================================================

    用户（macOS 15）反馈：登录界面正常，点确定之后**登录窗消失、
    鼠标一直转圈、主界面永远不出来、没有任何报错**。

    "转圈"= 主线程被卡住。用 `tests/repro_login.py` 的看门狗在
    **真 macOS runner** 上抓到的现场：

        ★ 卡死了：主线程已 20.4 秒没有任何进展
           最后一次进展：MainWindow.__init__ 结束   ← 窗口**已经建好了**
           平台：darwin
        --- 主线程调用栈 ---
           File "run_gui.py", line 230, in run_app   ← 卡在它的 mainloop()

    也就是说：主窗口对象建出来了，**它的 `mainloop()` 却收不到任何事件**
    （窗口不绘制、`after` 定时器永不触发）。而**第 1 个 root（登录窗）的
    `after` 回调是正常触发的** —— 对比之下结论很明确：

        在 macOS 上，一个进程里**第 2 个 `tk.Tk()` 的事件循环是不工作的**。
        Windows 的 Tk 扛得住，所以这个 bug 只在 mac 上出现，
        "登录可以、主界面不行"也正好由此解释（主界面要新建第 2 个 root）。

    试过的错路（都记下来，避免以后再走）：
      * 以为要避免"`mainloop` 嵌套"→ 改成顶层平级调用，**仍然卡**；
        因为问题不在嵌套，而在"第 2 个 root"本身。
      * 以为中文 locale 导致字体反复枚举 → 真机上 500 次调用只花 0.4ms，
        族名也不会被本地化。**那条推断是错的。**

    正确做法：**整个程序只建一个 `tk.Tk()`**（这里建，`withdraw()` 当宿主），
    主界面是它的 `tk.Toplevel`。

    ★★ 2026-10-04 用户要求：**删掉登录界面，只留一个主操控界面**
    =====================================================================
    所以现在没有"登录窗 → 主界面"这次窗口切换了 —— 启动就直接建主界面。
    这顺带把用户报的「输完账号密码后下一个界面没了」**整个环节去掉**了：
    不再有第二个窗口、不再有切换、不再有 destroy 后再建。

    Returns:
        进程退出码
    """
    from ui.main_window import MainWindow

    # ★★ 全进程唯一的 Tk root：只当事件循环宿主，自己不显示
    root = tk.Tk()
    root.withdraw()

    st = {"done": False, "error": False}

    def _stop() -> None:
        """结束事件循环（程序退出）。"""
        st["done"] = True
        try:
            root.quit()
        except Exception:
            pass

    _arm_watchdog()
    _beacon("开始创建主界面 MainWindow")
    try:
        MainWindow(root, on_quit=_stop)
    except Exception:
        _beacon("主界面创建失败")
        st["error"] = True
        _show_fatal("主界面启动失败：\n\n" + traceback.format_exc())
        return 1
    _beacon("主界面已创建，事件循环在跑")
    # ★ 主界面起来了 —— 之后主线程停在 mainloop 里是**正常**的，撤掉看门狗
    _disarm_watchdog()

    # ★ 全进程只调用这一次 mainloop（在唯一的 root 上）
    root.mainloop()
    return 1 if st["error"] else 0


# ================================================================ 启动看门狗
#
# ★★ 为什么需要（2026-10-04 用户 macOS 实测）
# ================================================================
# 现象：登录界面正常 → 点确定 → **登录窗消失、鼠标一直转圈、主界面永远不出来、
#       没有任何报错**。
#
# "转圈"= 主线程被卡住（不是崩溃），所以既没有异常也没有弹窗。
# 而这种"卡死"在别的机器上**复现不出来**（CI 的 macOS runner 上一路正常）。
#
# 没法复现就没法定位 —— 所以换个思路：**让卡死自己把现场写下来**。
# 这里起一个后台线程盯着"启动进度"，只要主线程超过 N 秒没动静，
# 就把**主线程的调用栈**（卡在哪一行）连同所有线程的栈写进
# `artifacts/logs/fatal.log`。用户那边一卡，日志里就有确切答案。
#
# 只在**启动阶段**武装；主界面起来后主线程停在 mainloop 是正常的，就撤掉。

_BEACON = {"label": "进程启动", "t": time.time()}
_WATCHDOG_ON = False
_HANG_SECONDS = float(os.getenv("XYX_HANG_SECONDS", "12") or 12)


def _beacon(label: str) -> None:
    """记一次"启动有进展"，并**顺手写一行到诊断文件**。

    ★ 为什么要写盘：万一用户在主线程卡死后**强制退出**（转圈时很容易这样做），
      看门狗可能还没到阈值、什么都没来得及写。有一条进度 trail 就能看出
      卡在哪一步（"创建登录窗" / "开始创建主界面 MainWindow" / "主界面已创建"）。
    """
    _BEACON["label"] = label
    _BEACON["t"] = time.time()
    try:
        p = Path.home() / "Desktop" / "XYXBot-诊断.txt"
        with open(p, "a", encoding="utf-8") as f:
            from datetime import datetime

            f.write(f"[{datetime.now():%H:%M:%S}] 启动进度：{label}\n")
    except Exception:
        pass


def _arm_watchdog() -> None:
    global _WATCHDOG_ON
    _WATCHDOG_ON = True
    _beacon("等待登录")


def _disarm_watchdog() -> None:
    global _WATCHDOG_ON
    _WATCHDOG_ON = False


def _dump_hang(idle: float, why: str = "主线程停滞") -> None:
    """把主线程卡在哪一行写进日志。"""
    frames = sys._current_frames()
    main_id = threading.main_thread().ident
    lines = [
        "=" * 68,
        f"★ 启动卡死报告（{why}）",
        f"  主线程已 {idle:.0f} 秒没有进展",
        f"  最后一次进展：{_BEACON['label']}",
        f"  平台：{sys.platform}  打包：{bool(getattr(sys, 'frozen', False))}",
        "=" * 68,
        "",
        "--- 主线程调用栈（最下面是最外层入口；卡住的那一行在最上面）---",
    ]
    fr = frames.get(main_id)
    if fr is not None:
        lines.extend(l.rstrip() for l in traceback.format_stack(fr))
    else:
        lines.append("  （拿不到主线程栈）")
    lines.append("")
    lines.append("--- 所有线程 ---")
    for tid, frame in frames.items():
        lines.append(f"# 线程 {tid}"
                     f"{'（主线程）' if tid == main_id else ''}")
        lines.extend("  " + l.rstrip()
                     for l in traceback.format_stack(frame))
    text = "\n".join(lines)
    print(text, file=sys.stderr)
    _log_fatal(text)


def _install_startup_watchdog() -> None:
    """启动看门狗（后台线程，不需要主线程配合）。"""
    def _loop() -> None:
        reported = 0
        while True:
            time.sleep(1.0)
            if not _WATCHDOG_ON:
                continue
            idle = time.time() - _BEACON["t"]
            if idle >= _HANG_SECONDS and reported < 3:
                reported += 1
                try:
                    _dump_hang(idle)
                except Exception:
                    pass
    threading.Thread(target=_loop, name="startup-watchdog",
                     daemon=True).start()


def main() -> None:
    # ★ 先装好回调异常处理器和启动看门狗，再创建任何窗口
    try:
        _install_error_handler()
    except Exception:
        pass
    try:
        _install_startup_watchdog()
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

        make_dpi_aware()
    except Exception:
        _show_fatal("初始化失败：\n\n" + traceback.format_exc())
        sys.exit(1)

    # ★ 顶层循环：登录窗 → 主界面。所有 mainloop() 都在 run_app 里平级调用，
    #   绝不嵌套（嵌套就是 macOS 上"登录后卡死"的根因，见 run_app 说明）。
    try:
        sys.exit(run_app())
    except Exception:
        _show_fatal("运行失败：\n\n" + traceback.format_exc())
        sys.exit(1)


if __name__ == "__main__":
    main()

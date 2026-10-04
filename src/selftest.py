"""环境自检：不开窗口，把「能不能跑起来」该看的都看一遍。

★★ 为什么单独做这个（2026-10-04 转 macOS + GitHub Actions）
========================================================

两个用途，都很实在：

1. **CI 里验证打好的包**。PyInstaller 打出来的 `XYXBot.app` 是 GUI 程序，
   在没人登录图形会话的 runner 上直接启动会失败 —— 那样"能不能跑"就验证不了。
   有了 `--selftest`，CI 可以在**不创建任何窗口**的前提下，
   检查包里的模块、Playwright driver、数据目录、浏览器内核是否齐全。

2. **用户排障**。macOS 上双击 .app 没反应是最常见的抱怨，但看不到任何输出。
   让用户执行
       /Applications/XYXBot.app/Contents/MacOS/XYXBot --selftest
   就能直接在终端看到是哪一环缺了。

设计原则：**只有"根本跑不起来"才算失败**（退出码 1），
"缺浏览器内核"这类是**警告**（退出码 0）—— 用户完全可以之后装个 Chrome。
"""

from __future__ import annotations

import os
import platform
import sys
import traceback
from pathlib import Path

__all__ = ["run_selftest", "collect_facts", "smoke_main_window"]


def _disp_width(s: str) -> int:
    """算显示宽度：中日韩字符占 2 列，其它占 1 列。

    ★ 不能用 `f"{s:<14}"` —— 那是按**字符个数**补空格，
      对中文标签会明显错位（对齐要靠显示宽度）。
    """
    import unicodedata

    w = 0
    for ch in s:
        w += 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
    return w


def _line(label: str, value: str, mark: str = "", width: int = 16) -> str:
    pad = max(1, width - _disp_width(label))
    return f"  {label}{' ' * pad}: {value}{('   ' + mark) if mark else ''}"


def collect_facts() -> dict:
    """把自检要用到的事实收集成 dict（便于测试断言，不打印）。

    Returns:
        {
          "platform": str, "arch": str, "python": str,
          "frozen": bool,
          "tkinter_ok": bool, "tkinter_detail": str,
          "display_ok": bool, "display_detail": str,
          "data_root": str, "data_writable": bool, "data_detail": str,
          "playwright_ok": bool, "playwright_detail": str,
          "browser_path": str, "browser_detail": str,
          "session_ok": bool, "session_detail": str,
          "errors": [str], "warnings": [str],
        }
    """
    f: dict = {
        "platform": sys.platform,
        "arch": platform.machine(),
        "os_version": platform.platform(),
        "python": sys.version.split()[0],
        "frozen": bool(getattr(sys, "frozen", False)),
        "errors": [],
        "warnings": [],
    }

    # ---- tkinter（GUI 的硬前提）----
    try:
        import tkinter  # noqa: F401

        f["tkinter_ok"] = True
        f["tkinter_detail"] = f"可用（Tk {tkinter.TkVersion}）"
    except Exception as e:
        f["tkinter_ok"] = False
        f["tkinter_detail"] = f"不可用：{type(e).__name__}: {e}"
        f["errors"].append("没有 tkinter，图形界面起不来")

    # ---- 有没有图形会话（没有也能跑 CLI，但 GUI 不行）----
    if f["tkinter_ok"]:
        try:
            import tkinter as tk

            r = tk.Tk()
            r.withdraw()
            r.destroy()
            f["display_ok"] = True
            f["display_detail"] = "可用"
        except Exception as e:
            f["display_ok"] = False
            f["display_detail"] = f"不可用（{type(e).__name__}）"
            f["warnings"].append(
                "当前环境没有图形会话 —— GUI 起不来，但打包/测试不受影响")
    else:
        f["display_ok"] = False
        f["display_detail"] = "跳过（没有 tkinter）"

    # ---- 数据目录（登录态/配置/细纲都写这里）----
    try:
        from src import config as C

        f["data_root"] = str(C.STORAGE.parent)
        probe = C.STORAGE / ".selftest-write-probe"
        C.STORAGE.mkdir(parents=True, exist_ok=True)
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        f["data_writable"] = True
        f["data_detail"] = "可写"
    except Exception as e:
        f["data_writable"] = False
        f.setdefault("data_root", "?")
        f["data_detail"] = f"不可写：{type(e).__name__}: {e}"
        f["errors"].append("数据目录不可写 —— 登录态与配置都存不下来")

    # ---- Playwright（含 driver 是否在包里）----
    try:
        from playwright._impl._driver import compute_driver_executable

        exe = compute_driver_executable()
        drv = exe[0] if isinstance(exe, (tuple, list)) else str(exe)
        exists = Path(str(drv)).exists()
        f["playwright_ok"] = bool(exists)
        try:
            from importlib.metadata import version as _pkgver

            ver = _pkgver("playwright")
        except Exception:
            ver = "?"
        f["playwright_detail"] = (
            f"{ver}（driver {'已打包' if exists else '缺失'}）")
        if not exists:
            f["errors"].append(
                "Playwright driver 不在包里 —— 浏览器根本起不来")
    except Exception as e:
        f["playwright_ok"] = False
        f["playwright_detail"] = f"不可用：{type(e).__name__}: {e}"
        f["errors"].append("Playwright 不可用")

    # ---- 浏览器内核（缺失只是警告）----
    try:
        from src.browser_detector import BrowserDetector

        path = BrowserDetector.get_recommended_browser()
        f["browser_path"] = path or ""
        if path:
            f["browser_detail"] = path
        else:
            f["browser_detail"] = ("未找到 Chrome/Edge —— "
                                   "需装一个，或执行 python -m playwright "
                                   "install chromium")
            f["warnings"].append(f["browser_detail"])
    except Exception as e:
        f["browser_path"] = ""
        f["browser_detail"] = f"检测失败：{type(e).__name__}: {e}"
        f["warnings"].append("浏览器检测失败")

    # ---- 登录态（只是信息）----
    try:
        from src import session as S

        d = S.describe()
        f["session_ok"] = bool(d.get("saved"))
        if f["session_ok"]:
            bits = [b for b in (d.get("account"), d.get("saved_at")) if b]
            f["session_detail"] = ("已保存"
                                   + (f"（{' · '.join(str(b) for b in bits)}）"
                                      if bits else ""))
        else:
            f["session_detail"] = "未保存（第一次用需要登录）"
    except Exception as e:
        f["session_ok"] = False
        f["session_detail"] = f"读取失败：{type(e).__name__}: {e}"

    return f


def _has_display() -> tuple:
    """(有没有可用图形会话, 说明)。"""
    try:
        import tkinter as tk

        r = tk.Tk()
        r.withdraw()
        r.destroy()
        return True, "可用"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def _probe_window(win, ms: int = 1200) -> dict:
    """让事件循环真的跑一小会儿，回报窗口**到底有没有显示出来**。

    ★★ 这一步是之前所有测试的盲区（2026-10-04）：
      之前的 GUI 测试只"构造"窗口、从不跑 mainloop，所以只能发现
      "构造时抛异常"，**发现不了"窗口建好了但没显示/没到前台"**。
      而用户反馈的正是"主界面出不来" —— 必须让事件循环跑起来才测得到。

    用 `after` 取一次状态然后 `quit()`，另加一个兜底 `after` 防止卡死，
    所以最多阻塞 ms+3000 毫秒。
    """
    res: dict = {}

    def _grab():
        try:
            res["mapped"] = bool(win.winfo_ismapped())
            res["viewable"] = bool(win.winfo_viewable())
            res["state"] = win.state()
            res["geometry"] = win.geometry()
            res["screen"] = f"{win.winfo_screenwidth()}x{win.winfo_screenheight()}"
        except Exception as e:
            res["error"] = f"{type(e).__name__}: {e}"
        try:
            win.quit()
        except Exception:
            pass

    try:
        win.after(ms, _grab)
        win.after(ms + 3000, win.quit)      # 兜底：绝不无限等
        win.mainloop()
    except Exception as e:
        res.setdefault("error", f"{type(e).__name__}: {e}")
    return res


def _visible(res: dict) -> tuple:
    """(是否真的显示出来了, 说明)。"""
    if res.get("error"):
        return False, f"探测出错：{res['error']}"
    st = res.get("state", "?")
    if res.get("viewable"):
        return True, f"已显示（state={st} {res.get('geometry')}）"
    return False, (f"**没显示出来**（state={st} mapped={res.get('mapped')} "
                   f"geometry={res.get('geometry')}）")


def smoke_main_window(verbose: bool = True) -> int:
    """★ 真的把「登录窗 → 主界面」这条路走一遍。

    ★★ 为什么必须做这个（2026-10-04 用户实测：macOS 上「输完授权码进不去」）
    =====================================================================

    打包成 .app 后 `console=False`，**stderr 是断的**。而真实流程是：

        LoginWindow._enter()          # 在 self.after(...) 回调里
            self.destroy()            # 登录窗先销毁
            self._on_success(user)    # → launch_main → MainWindow(...)
                                      #   这里一抛异常，Tk 就把它交给
                                      #   report_callback_exception，
                                      #   默认只 print 到 stderr（= 无处可去）

    用户看到的就是：登录窗消失、主界面不出现、**没有任何提示**。

    三种可能的根因，这里逐个覆盖：

      [1] 主窗口 / 某个页面构造时抛异常
          → 构造 MainWindow + 把 9 个页面都构建一遍
      [2] 窗口建出来了但**没显示出来/没到前台**（macOS 上"销毁再建 root"
          之后容易这样；构造成功所以什么都不报，用户就是"进不去"）
          → **跑真实事件循环**，检查 winfo_viewable()/state()
      [3] 打包产物缺模块（只有 .app 里才缺，源码跑没问题）
          → 这个函数在包内 `--selftest` 里也会跑，直接暴露

    Returns:
        0 = 都通过（或没有图形会话，跳过）；1 = 有失败
    """
    def _out(s: str) -> None:
        if verbose:
            print(s)

    ok, detail = _has_display()
    if not ok:
        _out(f"  跳过界面冒烟：当前没有图形会话（{detail}）")
        return 0

    rc = 0

    # ---- [1] 全新 root 构造主窗口 + 构建所有页面 ----
    _out("  [1/3] 构造主窗口，并逐个构建 9 个页面 …")
    try:
        from ui.main_window import MainWindow

        win = MainWindow(username="selftest")
        pages = ("run", "setup", "more", "overview", "account",
                 "books", "tasks", "settings", "about")
        failed_pages = []
        for key in pages:
            try:
                win.show_page(key)
            except Exception as e:
                failed_pages.append(f"{key}: {type(e).__name__}: {e}")
        if failed_pages:
            rc = 1
            _out("        ✗ 这些页面构建失败：")
            for f in failed_pages:
                _out("           " + f)
        else:
            _out("        ✓ 主窗口 + 9 个页面全部构建成功")
        try:
            win.destroy()
        except Exception:
            pass
    except Exception:
        rc = 1
        _out("        ✗ 主窗口构造失败：")
        for line in traceback.format_exc().splitlines():
            _out("           " + line)

    # ---- [2] 主窗口到底显示出来了没有（跑真实事件循环）----
    _out("  [2/3] 跑事件循环，检查主窗口是否真的显示出来 …")
    try:
        from ui.main_window import MainWindow

        win = MainWindow(username="selftest")
        probe = _probe_window(win)
        shown, why = _visible(probe)
        if shown:
            _out(f"        ✓ 主窗口已显示  {why}")
        else:
            rc = 1
            _out(f"        ✗ {why}")
        try:
            win.destroy()
        except Exception:
            pass
    except Exception:
        rc = 1
        _out("        ✗ 失败：")
        for line in traceback.format_exc().splitlines():
            _out("           " + line)

    # ---- [3] 复现真实顺序：登录窗 → 销毁 → 主窗口（带事件循环）----
    _out("  [3/3] 复现真实顺序：登录窗 → 销毁 → 主窗口（两个 root 都跑事件循环）…")
    try:
        from ui.login_window import LoginWindow
        from ui.main_window import MainWindow

        lw = LoginWindow(on_success=lambda u: None)
        p1 = _probe_window(lw)
        s1, w1 = _visible(p1)
        _out(f"        {'✓' if s1 else '✗'} 登录窗：{w1}")
        lw.destroy()

        win2 = MainWindow(username="selftest")
        p2 = _probe_window(win2)
        s2, w2 = _visible(p2)
        if s2:
            _out(f"        ✓ 登录窗销毁后，主窗口仍能正常显示：{w2}")
        else:
            rc = 1
            _out("        ✗ **这就是「输完授权码进不去主界面」** —— 登录窗没了，"
                 "主窗口建出来了但没显示：")
            _out(f"           {w2}")
            _out(f"           （登录窗当时是：{w1}）")
        if not s1:
            _out("        ⚠ 登录窗本身也没探到「已显示」（可能只是探测时机问题）")
        try:
            win2.destroy()
        except Exception:
            pass
    except Exception:
        rc = 1
        _out("        ✗ 失败 —— 这正是「输完授权码进不去主界面」的那条路：")
        for line in traceback.format_exc().splitlines():
            _out("           " + line)

    return rc


def run_selftest(verbose: bool = True, smoke_ui: bool = False) -> int:
    """跑一遍自检并打印。返回进程退出码（0 = 可以启动）。

    Args:
        verbose:  是否打印明细
        smoke_ui: 是否额外**真的把界面构造一遍**（见 `smoke_ui`）。
                  命令行的 `--selftest` 默认开；程序内部调用默认关。
    """
    f = collect_facts()

    if verbose:
        print("=" * 66)
        print("  星月创作台 · 环境自检（不会打开窗口）")
        print("=" * 66)
        print(_line("运行方式",
                    "打包版（.app/.exe）" if f["frozen"] else "源码运行"))
        print(_line("平台/架构", f"{f['platform']} / {f['arch']}"))
        print(_line("系统", f["os_version"]))
        print(_line("Python", f["python"]))
        print(_line("tkinter", f["tkinter_detail"],
                    "" if f["tkinter_ok"] else "✗"))
        print(_line("图形会话", f["display_detail"],
                    "" if f["display_ok"] else "（仅警告）"))
        print(_line("数据目录", f["data_root"]))
        print(_line("数据可写", f["data_detail"],
                    "" if f["data_writable"] else "✗"))
        print(_line("Playwright", f["playwright_detail"],
                    "" if f["playwright_ok"] else "✗"))
        print(_line("浏览器内核", f["browser_detail"],
                    "" if f["browser_path"] else "（仅警告）"))
        print(_line("登录态", f["session_detail"]))

    # ---- 界面能不能真的构造起来 ----
    ui_rc = 0
    if smoke_ui and f["tkinter_ok"]:
        if verbose:
            print("-" * 66)
            print("  界面构造冒烟（重点：打包后最容易出问题的部分）")
        # ★ 注意别写成 smoke_ui(...) —— 那是本函数的参数名，会遮蔽同名函数
        ui_rc = smoke_main_window(verbose)

    if verbose:
        print("-" * 66)
        if f["errors"]:
            print("  ✗ 有阻塞问题，程序无法正常运行：")
            for e in f["errors"]:
                print(f"      · {e}")
        elif ui_rc != 0:
            print("  ✗ 环境本身没问题，但**界面构造失败**（见上面的堆栈）")
        else:
            print("  ✓ 核心依赖齐全，界面也能构造起来")
        if f["warnings"]:
            print("  ⚠ 提醒（不影响启动）：")
            for w in f["warnings"]:
                print(f"      · {w}")
        print("=" * 66)

    return 1 if (f["errors"] or ui_rc != 0) else 0


if __name__ == "__main__":
    sys.exit(run_selftest(smoke_ui="--no-ui" not in sys.argv))

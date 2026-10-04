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
import time
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

    # ---- 字体：中文 Mac 上最容易出问题、也最难远程排查的一项 ----
    try:
        from ui.theme import font_report

        f["font"] = font_report()
        fr = f["font"]
        m = fr.get("ui_matched")
        state = ("命中候选" if m else
                 ("候选未命中，用了回退" if m is False else "未定稿"))
        f["font_detail"] = (
            f"{fr.get('ui')}（{state}）"
            + f" · 系统 {fr.get('system_family_count')} 个字体族"
            f" · 枚举 {fr.get('families_ms')} ms"
            + f" · 等宽 {fr.get('mono')}")
        if m is False:
            f["warnings"].append(
                f"界面字体没匹配上候选（实际用 {fr.get('ui')}）—— "
                "中文显示可能不正常，可用 XYX_UI_FONT 指定")
    except Exception as e:
        f["font"] = {}
        f["font_detail"] = f"读取失败：{type(e).__name__}: {e}"

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
    """用 `update()` 泵事件，检查窗口**到底有没有显示出来**。

    ★★★ 为什么不用 `mainloop()` + `after`（2026-10-04 关键突破）
    =====================================================================
    原来这里是 `win.after(ms, ...)` + `win.mainloop()`。实测在 **GitHub 的
    macOS runner** 上，`mainloop()` **根本不处理定时器事件**（没有真实窗口
    会话，CFRunLoop 的定时器源不被唤醒）—— 于是 `after` 回调永远不触发，
    我只能看到"没进展"，还一度把这条路径当成 runner 限制绕过去了，
    结果真正的 bug（渲染风暴）和"窗口到底有没有显示"都验不出来。

    `update()` 是"把所有**当前就绪**的事件处理掉"，包含已到期的定时器，
    **不依赖 CFRunLoop 定时器源**。所以用它泵事件既能驱动真实流程，
    也能可靠地检查 `winfo_viewable()`。

    Args:
        win: 要观察的窗口
        ms: 最多泵多少毫秒

    Returns:
        {visible, geometry, state, secs, iters, error}
    """
    res = {"visible": False, "geometry": None, "state": None,
           "secs": None, "iters": 0}
    t0 = time.time()
    limit = max(0.05, ms / 1000.0)
    if sys.platform == "darwin":
        limit = max(limit, 6.0)      # macOS 上首帧要等窗口服务，给足时间
    while time.time() - t0 < limit:
        try:
            win.update()
        except Exception as e:
            res["error"] = f"{type(e).__name__}: {e}"
            break
        res["iters"] += 1
        try:
            if win.winfo_viewable():
                res["visible"] = True
                res["geometry"] = win.geometry()
                res["state"] = win.state()
                res["secs"] = round(time.time() - t0, 2)
                break
        except Exception:
            pass
        time.sleep(0.005)
    return res


def _visible(res: dict) -> tuple:
    """(是否真的显示出来了, 说明)。"""
    if res.get("error"):
        return False, f"探测出错：{res['error']}"
    if res.get("visible"):
        return True, (f"已显示（{res.get('geometry')} state={res.get('state')}"
                      f"，{res.get('secs')}s）")
    return False, (f"**没有显示出来**（泵了 {res.get('iters')} 次 update()，"
                   f"viewable=False geometry={res.get('geometry')} "
                   f"state={res.get('state')}）")


def _screencapture(name: str) -> str | None:
    """macOS 上截一张全屏图（用于"窗口到底出没出来"的存证）。失败返回 None。"""
    if not sys.platform.startswith("darwin"):
        return None
    try:
        import subprocess

        from src import config as C

        p = C.SHOTS / name
        r = subprocess.run(["screencapture", "-x", str(p)],
                           capture_output=True, timeout=20)
        if r.returncode == 0 and p.exists():
            return str(p)
    except Exception:
        pass
    return None


def _window_probe_wanted() -> bool:
    """要不要做「窗口真的显示出来了吗」的探测。**默认关闭，需显式开启。**

    ★★ 为什么默认关（2026-10-04 实测踩了两次）
    =====================================================================
    这个探测必须驱动 Tk 事件循环（先试 `mainloop()`+`after`，后改 `update()`
    泵）。**两种写法在 GitHub 的 macOS runner 上都会阻塞** —— 那台 runner
    没有真实窗口会话，一碰事件循环就卡住，把 job 拖到超时。

    所以：
      * 默认**不做**（`--selftest` 干净、快，CI 里当硬断言用）；
      * 要验证"窗口到底显不显示"时显式开：
          - `XYX_SELFTEST_WINDOW=1`，或命令行 `--window`
          - CI 里放在**单独一步 + `timeout`** 里跑，只认明确结论，
            超时就跳过（见 `.github/workflows/build-macos.yml`）。
      * 用户自己的 Mac 有真实桌面会话，开了就能拿到结论。
    """
    v = os.getenv("XYX_SELFTEST_WINDOW", "").strip().lower()
    return v in ("1", "true", "yes", "on")


def smoke_main_window(verbose: bool = True,
                      window_probe: bool | None = None) -> int:
    """★ 把界面这条路真的走一遍（构造 + 可选地验证"真的显示出来了"）。

    ★★ 为什么必须做这个（2026-10-04 用户实测：macOS 上「登录后界面没了」）
    =====================================================================

    打包成 .app 后 `console=False`，**stderr 是断的**：回调里的异常默认只
    `print` 到 stderr（= 无处可去），用户看到的就是"点了没反应、什么都不显示"。

    ★ 2026-10-04 按用户要求**删掉了登录界面**，只留一个主操控界面 ——
      所以原来那条「登录窗 → 销毁 → 主窗」的切换路径**整个不存在了**，
      用户报的问题也就没有了发生的场所。

    现在覆盖三件事：

      [1] 主窗口 / 某个页面构造时抛异常，或打包产物缺模块
          → 构造 MainWindow + 把 9 个页面都构建一遍（**不映射窗口**，
            所以任何环境都能安全跑，包括 CI）
      [2] 窗口建出来了但**没显示出来/没到前台**
          → 跑真实事件循环，检查 `winfo_viewable()`/`state()`
          ★ 这一步会真的显示窗口；因为它在**没有真实窗口会话**的 CI runner
            上会阻塞，所以默认关闭（见 `_window_probe_wanted`），
            CI 里放在单独一步 + `timeout` 跑
      [3] 关窗要能通知外层、让事件循环退出
          → 单 root 架构下，窗口没了但循环还活着 = "看不见却活着"的进程

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

    if window_probe is None:
        window_probe = _window_probe_wanted()
    n_steps = 3 if window_probe else 2

    # ★★★ 只建**一个** Tk root，主窗口是它的 Toplevel —— 和
    #     `run_gui.run_app` 的真实结构一致（也是 macOS 上唯一能用的结构：
    #     一个进程里第 2 个 `tk.Tk()` 的事件循环收不到任何事件）。
    #     （tkinter 在函数内 import：没装 tkinter 的环境也能用这个模块做环境检查）
    import tkinter as tk

    root = tk.Tk()
    root.withdraw()

    rc = 0

    # ---- [1] 构造主窗口 + 构建所有页面（不显示窗口，任何环境都安全）----
    _out(f"  [1/{n_steps}] 构造主窗口，并逐个构建 9 个页面 …")
    try:
        from ui.main_window import MainWindow

        win = MainWindow(root, username="selftest")
        win.withdraw()          # 这一步只验证"能不能构造"，不需要显示
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

    # ---- [2] 窗口到底显示出来了没有（只在允许时做）----
    if window_probe:
        _out("  [2/3] 用 update() 泵事件，检查主窗口是否真的显示出来 …")
        try:
            from ui.main_window import MainWindow

            win = MainWindow(root, username="selftest")
            probe = _probe_window(win)
            shown, why = _visible(probe)
            if shown:
                _out(f"        ✓ 主窗口已显示  {why}")
                # ★ macOS 上顺手截个图：CI 里可以直接看"窗口到底长什么样/有没有"
                _p = _screencapture("selftest_main_window.png")
                if _p:
                    _out(f"        （已截图 {_p}）")
                # ★★ 2026-10-04 新增：逐页真的切一遍并确认每页都显示出来。
                #    用户要求「在 mac 上测一下所有功能是否正常」——
                #    光验证"主窗口显示"不够，9 个页面各自能不能显示、切页会不会
                #    出错才是真正用得到的东西。这里在**真实事件循环**下逐页切。
                bad = []
                for _k in ("run", "setup", "more", "overview", "account",
                           "books", "tasks", "settings", "about"):
                    try:
                        win.show_page(_k)
                        root.update_idletasks()
                        root.update()
                        _fr = win._pages.get(_k)
                        _vw = bool(_fr.winfo_viewable()) if _fr else False
                        _gw = _fr.winfo_width() if _fr else 0
                        _gh = _fr.winfo_height() if _fr else 0
                        _lbl = win._page_labels().get(_k, _k)
                        if _vw and _gw > 1 and _gh > 1:
                            _out(f"        ✓ 页面「{_lbl}」显示正常 "
                                 f"（{_gw}x{_gh}）")
                        else:
                            bad.append(f"{_k}（viewable={_vw} {_gw}x{_gh}）")
                    except Exception as e:
                        bad.append(f"{_k}: {type(e).__name__}: {e}")
                if bad:
                    rc = 1
                    _out("        ✗ 这些页面没能正常显示：")
                    for _b in bad:
                        _out("           " + _b)
                else:
                    _out("        ✓ 9 个页面逐个切换，全部显示正常")
                # 切回默认页再截图，画面更有代表性
                try:
                    win.show_page("run")
                    root.update()
                except Exception:
                    pass
            else:
                rc = 1
                _out(f"        ✗ {why}")
                _p = _screencapture("selftest_main_window_FAILED.png")
                if _p:
                    _out(f"        （已截图 {_p} —— 看看屏幕上到底有什么）")
            try:
                win.destroy()
            except Exception:
                pass
        except Exception:
            rc = 1
            _out("        ✗ 失败：")
            for line in traceback.format_exc().splitlines():
                _out("           " + line)

    # ---- [3] 关掉主窗口后，事件循环还能正常收尾 ----
    #  ★ 2026-10-04 删掉登录界面后，这里不再复现"登录窗→主窗口"的切换
    #    （那次切换正是用户报的「下一个界面没了」发生的地方，现在整个没了）。
    #    改成验证另一件真实存在的事：**关窗要能干净退出**（单 root 架构下
    #    窗口没了但事件循环还活着，就会变成"看不见却活着"的进程）。
    label = "[3/3]" if window_probe else "[2/2]"
    _out(f"  {label} 关窗后事件循环要能正常收尾 …")
    try:
        from ui.main_window import MainWindow

        flag: dict = {}
        win2 = MainWindow(root, username="selftest",
                          on_quit=lambda: flag.setdefault("quit", True))
        if window_probe:
            p2 = _probe_window(win2)
            s2, w2 = _visible(p2)
            _out(f"        {'✓' if s2 else '✗'} 主窗口：{w2}")
            if not s2:
                rc = 1
        else:
            win2.withdraw()
        win2._on_window_close()          # 走真实的关窗路径
        if flag.get("quit"):
            _out("        ✓ 关窗通知到了外层（事件循环能退出）")
        else:
            rc = 1
            _out("        ✗ 关窗没有通知外层 —— 会变成「看不见却活着」的进程")
    except Exception:
        rc = 1
        _out("        ✗ 失败：")
        for line in traceback.format_exc().splitlines():
            _out("           " + line)

    try:
        root.destroy()
    except Exception:
        pass
    return rc


def run_selftest(verbose: bool = True, smoke_ui: bool = False,
                 window_probe: bool | None = None) -> int:
    """跑一遍自检并打印。返回进程退出码（0 = 可以启动）。

    Args:
        verbose:      是否打印明细
        smoke_ui:     是否额外**真的把界面构造一遍**
                      （见 `smoke_main_window`）。
                      命令行的 `--selftest` 默认开；程序内部调用默认关。
        window_probe: 界面冒烟里是否做「窗口真的显示了吗」的探测（会跑事件
                      循环、会真的显示窗口）。None = 自动判断：用户本机开，
                      **CI 环境自动关**（在 macOS runner 上会卡死，
                      详见 `_window_probe_wanted`）。
    """
    f = collect_facts()

    if verbose:
        print("=" * 66)
        print("  星月创作台 · 环境自检（不会打开窗口）")
        print("=" * 66)
        print(_line("运行方式",
                    "打包版（.app/.exe）" if f["frozen"] else "源码运行"))
        try:
            from src import _buildinfo as _B

            print(_line("构建版本", _B.describe()))
        except Exception:
            pass
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
        print(_line("界面字体", f.get("font_detail", "?")))
        print(_line("登录态", f["session_detail"]))

    # ---- 界面能不能真的构造起来 ----
    ui_rc = 0
    if smoke_ui and f["tkinter_ok"]:
        if verbose:
            print("-" * 66)
            print("  界面构造冒烟（重点：打包后最容易出问题的部分）")
        # ★ 注意别写成 smoke_ui(...) —— 那是本函数的参数名，会遮蔽同名函数
        ui_rc = smoke_main_window(verbose, window_probe=window_probe)
        if verbose and window_probe is False:
            print("        （未做窗口显示探测：自动化环境默认关闭，"
                  "可用 --window 强制打开）")

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
    _wp = None
    if "--window" in sys.argv:
        _wp = True
    elif "--no-window" in sys.argv:
        _wp = False
    sys.exit(run_selftest(smoke_ui="--no-ui" not in sys.argv,
                          window_probe=_wp))

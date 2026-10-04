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
from pathlib import Path

__all__ = ["run_selftest", "collect_facts"]


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


def run_selftest(verbose: bool = True) -> int:
    """跑一遍自检并打印。返回进程退出码（0 = 可以启动）。"""
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
        print("-" * 66)
        if f["errors"]:
            print("  ✗ 有阻塞问题，程序无法正常运行：")
            for e in f["errors"]:
                print(f"      · {e}")
        else:
            print("  ✓ 核心依赖齐全，可以启动")
        if f["warnings"]:
            print("  ⚠ 提醒（不影响启动）：")
            for w in f["warnings"]:
                print(f"      · {w}")
        print("=" * 66)

    return 1 if f["errors"] else 0


if __name__ == "__main__":
    sys.exit(run_selftest())

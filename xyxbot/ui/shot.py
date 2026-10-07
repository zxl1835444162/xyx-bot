"""UI 截图工具：把窗口渲染成 PNG，用于开发期视觉验证。

Windows 上直接用 Win32 GetWindowRect 取窗口真实矩形，再用 PIL 截屏，
避免 winfo_rootx 在多窗口/DPI 场景下偏移。
"""

from __future__ import annotations

import ctypes
import sys
import time
from pathlib import Path


def make_dpi_aware() -> None:
    """开启 DPI 感知，避免高分屏下坐标错位。"""
    if not sys.platform.startswith("win"):
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def grab_window(win, out_path: str | Path) -> Path:
    """把 tk 窗口截成图片。"""
    from PIL import ImageGrab

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    # 让窗口在最前并完成绘制
    win.update_idletasks()
    win.update()
    try:
        win.lift()
        win.attributes("-topmost", True)
        win.focus_force()
    except Exception:
        pass
    for _ in range(10):
        win.update()
    time.sleep(0.9)
    win.update()

    l = t = r = b = None
    if sys.platform.startswith("win"):
        import ctypes.wintypes as wt

        rect = wt.RECT()
        ctypes.windll.user32.GetWindowRect(win.winfo_id(), ctypes.byref(rect))
        l, t, r, b = rect.left, rect.top, rect.right, rect.bottom

    if l is None:
        l, t = win.winfo_rootx(), win.winfo_rooty()
        r, b = l + win.winfo_width(), t + win.winfo_height()

    ImageGrab.grab(bbox=(l, t, r, b)).save(str(out))

    try:
        win.attributes("-topmost", False)
    except Exception:
        pass
    return out

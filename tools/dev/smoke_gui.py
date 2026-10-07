# -*- coding: utf-8 -*-
"""GUI 冒烟 + 截图：把新界面真渲染出来，存成 PNG 供人工/自动核对。

为什么要这个：本轮是**界面重设计**，光靠"控件都存在"的断言看不出
布局是不是真的可用（挤在一起、被裁掉、空白过大都测不出来）。
所以这里真的把窗口画出来、截图。

用法：
    .venv312\\Scripts\\python.exe smoke_gui.py
产物：
    artifacts/screenshots/ui-run.png / ui-setup.png / ui-more.png
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # 仓库根（tools/<组>/ -> tools -> 根）
sys.path.insert(0, str(ROOT))

_PAGES = [("run", "ui-run"), ("setup", "ui-setup"), ("more", "ui-more")]


def main() -> int:
    try:
        from src.console import enable_utf8

        enable_utf8()
    except Exception:
        pass

    from ui.shot import grab_window, make_dpi_aware

    make_dpi_aware()

    # ★ 没有窗口服务器时优雅跳过（CI runner 通常没有图形会话）
    try:
        import tkinter as tk

        _r = tk.Tk()
        _r.withdraw()
        _r.destroy()
    except Exception as e:
        print(f"[smoke] SKIP：没有可用的窗口服务器（{type(e).__name__}: "
              f"{str(e)[:100]}）")
        return 0

    from ui.main_window import MainWindow

    win = MainWindow(username="tester")
    win.geometry("1180x980")
    win.update_idletasks()
    win.deiconify()
    win.lift()

    out_dir = ROOT / "artifacts" / "screenshots"
    out_dir.mkdir(parents=True, exist_ok=True)

    state = {"i": 0}

    def step():
        i = state["i"]
        if i >= len(_PAGES):
            print("[smoke] 全部截图完成")
            try:
                win.destroy()
            except Exception:
                pass
            os._exit(0)

        key, name = _PAGES[i]
        win.show_page(key)
        win.update_idletasks()
        win.update()
        try:
            p = grab_window(win, out_dir / f"{name}.png")
            print(f"[smoke] {key:8s} -> {p}  "
                  f"({win.winfo_width()}x{win.winfo_height()})")
        except Exception as e:
            print(f"[smoke] {key} 截图失败：{e}")
        state["i"] = i + 1
        win.after(700, step)

    win.after(900, step)
    try:
        win.mainloop()
    except Exception as e:
        print(f"[smoke] mainloop 退出：{e}")
    os._exit(0)


if __name__ == "__main__":
    sys.exit(main())

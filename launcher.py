"""启动器：自动挑一个**带 tkinter** 的 Python 来跑图形界面。

Windows / macOS / Linux 通用：
    python launcher.py           # 启动 GUI
    python launcher.py cli ...   # 透传给 main.py（命令行模式）

★ 2026-10-04 转 macOS 时改的：
  原来只会找 `.venv312\\Scripts\\python.exe` 这类 Windows 路径，
  在 macOS 上永远找不到解释器、直接提示"未找到带 tkinter 的 Python"。
  现在按平台给出候选（POSIX 下是 `bin/python3`），并且**优先用当前解释器**
  —— 既然它已经在跑这个脚本了，多半就是对的。
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

_BIN = "Scripts" if os.name == "nt" else "bin"
_EXE = "python.exe" if os.name == "nt" else "python3"

# 候选解释器（按优先级）：能 import tkinter 的即可用
CANDIDATES = [
    ROOT / ".venv312" / _BIN / _EXE,      # 带 tkinter 的专用环境
    ROOT / ".venv" / _BIN / _EXE,         # 通用环境
    Path(sys.executable),                 # ★ 正在跑本脚本的解释器
    Path("/usr/bin/python3"),             # macOS 系统 Python
    Path("/usr/local/bin/python3"),       # Homebrew (Intel)
    Path("/opt/homebrew/bin/python3"),    # Homebrew (Apple Silicon)
    Path(r"C:\Python312\python.exe"),     # Windows 系统 Python
]


def has_tkinter(exe: Path) -> bool:
    """这个解释器能不能 import tkinter（也就是能不能跑 GUI）。"""
    try:
        r = subprocess.run(
            [str(exe), "-c", "import tkinter"],
            capture_output=True, timeout=20,
        )
        return r.returncode == 0
    except Exception:
        return False


def pick_python() -> Path | None:
    seen: set[str] = set()
    for exe in CANDIDATES:
        try:
            key = str(exe.resolve())
        except Exception:
            key = str(exe)
        if key in seen:
            continue
        seen.add(key)
        if exe.exists() and has_tkinter(exe):
            return exe
    return None


def main() -> None:
    # CLI 透传模式
    if len(sys.argv) > 1 and sys.argv[1] == "cli":
        subprocess.run([sys.executable, str(ROOT / "main.py"), *sys.argv[2:]])
        return

    exe = pick_python()
    if exe is None:
        print("未找到带 tkinter 的 Python 环境。")
        if sys.platform == "darwin":
            print("macOS 上建议用 python.org 的官方安装包（自带 tkinter），"
                  "或：brew install python-tk")
        else:
            print("请安装完整版 Python（含 tkinter），"
                  "或运行 build.bat 创建环境。")
        try:
            input("按回车退出...")
        except Exception:
            pass
        return

    print(f"使用解释器：{exe}")
    sys.exit(subprocess.run([str(exe), str(ROOT / "run_gui.py")]).returncode)


if __name__ == "__main__":
    main()

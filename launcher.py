"""环境入口：保证有可用的运行环境，然后启动界面或命令行。

这是**唯一**决定"用哪个 Python、装哪些依赖"的地方 —— 以前这套逻辑散在
`启动.bat` / `start.bat` / `build.bat` / `launcher.py` 四处，还各自写死了
本机专属的解释器路径（`C:\\Python312\\...`、`.workbuddy\\...`），
换一台机器就挂。现在都收敛到这里：

    启动.bat          → python launcher.py            （图形界面）
    python launcher.py --setup                        （只准备环境，不启动）
    python launcher.py cli selftest                   （命令行，透传给 main.py）
    python launcher.py cli ai continue --from 3       （同上，参数原样透传）

环境策略
--------
* 只在仓库根的 `.venv/` 建**一个**环境（以前 GUI 用 `.venv312`、CLI 用 `.venv`，
  用户得记住哪个是哪个，是"纸糊感"的来源之一）。
* 建环境用的基解释器必须**带 tkinter**（否则建出来的 venv 跑不了界面）——
  venv 不复制 tkinter，它依赖基解释器。
* 依赖装 `requirements-gui.txt`（= playwright + Pillow），GUI 与 CLI 共用。
* 当前解释器已经满足条件就直接用，不折腾（少一次 40 MB 的下载）。
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"
REQ = ROOT / "requirements-gui.txt"
GUI_ENTRY = ROOT / "run_gui.py"
CLI_ENTRY = ROOT / "main.py"

_BIN = "Scripts" if os.name == "nt" else "bin"
_EXE = "python.exe" if os.name == "nt" else "python3"
VENV_PY = VENV / _BIN / _EXE

# GUI 跑起来需要的模块：tkinter 是界面，playwright 是自动化，PIL 是截图/图标
NEEDED = "import tkinter, playwright, PIL"

# 建环境用的候选基解释器（按优先级）。故意不放任何本机专属路径。
CANDIDATES = [
    Path(sys.executable),                 # 正在跑本脚本的解释器，优先
    VENV_PY,                              # 已建好的环境
    Path("/usr/bin/python3"),             # macOS / Linux 系统 Python
    Path("/usr/local/bin/python3"),       # Homebrew (Intel Mac)
    Path("/opt/homebrew/bin/python3"),    # Homebrew (Apple Silicon)
]


def _ok(exe: Path, code: str = NEEDED) -> bool:
    """这个解释器能不能 import 指定模块。"""
    try:
        r = subprocess.run([str(exe), "-c", code], capture_output=True, timeout=60)
        return r.returncode == 0
    except Exception:
        return False


def _has_tkinter(exe: Path) -> bool:
    return _ok(exe, "import tkinter")


def _discover() -> list[Path]:
    """把本机**所有**能想到的解释器都找出来。

    光看 `sys.executable` 不够：Windows 上 `py -3` 可能挑到没装 tkinter 的新版本，
    而用户真正能跑界面的那个（比如 3.12）在旁边闲着。所以让 `py -0p` 把清单交出来。
    """
    found: list[Path] = []
    if os.name == "nt":
        try:
            r = subprocess.run(["py", "-0p"], capture_output=True, text=True, timeout=20)
            for line in (r.stdout or "").splitlines():
                # 形如： -V:3.12 *        C:\Python312\python.exe
                for token in line.split():
                    if token.lower().endswith("python.exe"):
                        found.append(Path(token))
        except Exception:
            pass
    else:
        for name in ("python3", "python3.13", "python3.12", "python3.11"):
            try:
                r = subprocess.run(["which", name], capture_output=True, text=True, timeout=10)
                p = (r.stdout or "").strip()
                if p:
                    found.append(Path(p))
            except Exception:
                pass
    return found


def pick_base() -> Path | None:
    """挑一个带 tkinter 的基解释器（用来建 venv）。"""
    seen: set[str] = set()
    for exe in [*CANDIDATES, *_discover()]:
        try:
            key = str(exe.resolve())
        except Exception:
            key = str(exe)
        if key in seen:
            continue
        seen.add(key)
        if exe.exists() and _has_tkinter(exe):
            return exe
    return None


def ensure_env(verbose: bool = True) -> Path | None:
    """返回一个能跑 GUI/CLI 的解释器；必要时现建环境并装依赖。"""
    # 1) 当前解释器已经够用 → 直接用
    if _ok(Path(sys.executable)):
        return Path(sys.executable)

    # 2) 已有 .venv 且依赖齐 → 直接用
    if VENV_PY.exists() and _ok(VENV_PY):
        return VENV_PY

    # 3) 建环境。基解释器必须带 tkinter，否则界面跑不起来
    base = pick_base()
    if base is None:
        print("找不到可用的 Python 环境（需要一个带 tkinter 的 Python）。")
        if sys.platform == "darwin":
            print("macOS 建议用 python.org 官方安装包（自带 tkinter），或：brew install python-tk")
        else:
            print("请到 https://www.python.org/downloads/ 安装，安装时勾选 tcl/tk 与 Add python.exe to PATH")
        return None

    if verbose:
        print(f"[环境] 用这个解释器建环境：{base}")
    if not VENV_PY.exists():
        r = subprocess.run([str(base), "-m", "venv", str(VENV)])
        if r.returncode != 0 or not VENV_PY.exists():
            print("[环境] 创建虚拟环境失败。")
            return None

    if verbose:
        print(f"[环境] 安装依赖（{REQ.name}）…首次约 1-3 分钟")
    r = subprocess.run([str(VENV_PY), "-m", "pip", "install", "-q", "--upgrade", "pip"])
    r = subprocess.run([str(VENV_PY), "-m", "pip", "install", "-q", "-r", str(REQ)])
    if r.returncode != 0 or not _ok(VENV_PY):
        print("[环境] 依赖安装失败。可手动执行：")
        print(f'    "{VENV_PY}" -m pip install -r "{REQ}"')
        return None

    if verbose:
        print("[环境] 准备完成。")
    return VENV_PY


def run(exe: Path, entry: Path, args: list[str]) -> int:
    return subprocess.run([str(exe), str(entry), *args]).returncode


def main() -> None:
    argv = sys.argv[1:]
    setup_only = "--setup" in argv
    if setup_only:
        argv = [a for a in argv if a != "--setup"]

    exe = ensure_env()
    if exe is None:
        _pause()
        sys.exit(1)

    if setup_only:
        print(f"环境就绪：{exe}")
        return

    # 命令行模式：python launcher.py cli <命令> [参数...]
    if argv and argv[0] == "cli":
        sys.exit(run(exe, CLI_ENTRY, argv[1:]))

    sys.exit(run(exe, GUI_ENTRY, argv))


def _pause() -> None:
    """双击运行时别让窗口一闪而过（自动化环境没有 stdin，忽略报错）。"""
    try:
        input("按回车退出…")
    except Exception:
        pass


if __name__ == "__main__":
    main()

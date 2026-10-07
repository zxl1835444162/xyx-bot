"""测试的"文件布局"唯一接口。

**为什么要有这个文件**

重构前，全项目 32 处测试直接拼路径或按函数名切源码文本，例如：

    ai_src = (ROOT / "src" / "ai.py").read_text(encoding="utf-8")
    _vis_src = ai_src.split("def _visible(")[1].split("def _present(")[0]
    _spec 里必须出现 '"src"' 和 '"ui"'

这等于把**文件名和函数顺序**写进了断言：把 `ai.py` 拆开、把函数挪个位置，
测试立刻红 —— 哪怕行为一点没变。于是没人敢动结构，项目只能"往上加"。
现在所有"文件长在哪"的问题都只问这个模块，重构时只改这一处。

**用法**

    import _support as S            # 同目录，测试直接 import
    S.ROOT / S.PKG / S.UI / S.TOOLS / S.DOCS
    S.pkg_file("ai.py")             # 业务包里的文件（自动跟随 src→xyxbot 改名）
    S.ui_file("theme.py")           # 界面文件
    S.read(S.pkg_file("ai.py"))     # 读源码文本（旧测试的静态审计继续可用）
    S.add_tools_to_path()           # 让测试能 import tools/ 下的开发脚本
    S.find_def("wait_generation")   # 在业务包里定位某个函数的源码（拆分后仍然找得到）
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

#: 业务包目录。Phase B 把 `src/` 改名成 `xyxbot/` 之后这里自动跟随，测试无需改。
PKG_NAME = "xyxbot" if (ROOT / "xyxbot").is_dir() else "src"
PKG = ROOT / PKG_NAME

#: 界面目录：改名后收进包里（xyxbot/ui），之前是平级的 ui/
UI = (PKG / "ui") if (PKG / "ui").is_dir() else (ROOT / "ui")

TOOLS = ROOT / "tools"
DOCS = ROOT / "docs"
TESTS = ROOT / "tests"


def pkg_file(*parts: str) -> Path:
    return PKG.joinpath(*parts)


def ui_file(*parts: str) -> Path:
    return UI.joinpath(*parts)


def read(path: Path) -> str:
    """读源码文本（静态审计用）。统一 utf-8，避免 Windows 上 GBK 乱码。"""
    return Path(path).read_text(encoding="utf-8")


def read_if_exists(path: Path, default: str = "") -> str:
    p = Path(path)
    return read(p) if p.exists() else default


def pkg_py_files():
    """业务包里所有 .py（含子包）。"""
    return sorted(PKG.rglob("*.py"))


def ui_py_files():
    """界面所有 .py（含 pages/）。"""
    return sorted(UI.rglob("*.py"))


def all_source_files():
    """业务包 + 界面（旧测试里到处在拼这个列表）。"""
    return [*ui_py_files(), *pkg_py_files()]


def add_tools_to_path() -> None:
    """让测试能 import tools/ 下的开发脚本（它们以前躺在仓库根目录）。"""
    for sub in ("audit", "diag", "dev", "scratch"):
        p = TOOLS / sub
        if p.is_dir() and str(p) not in sys.path:
            sys.path.insert(0, str(p))
    if str(TOOLS) not in sys.path:
        sys.path.insert(0, str(TOOLS))


def find_def(func_name: str):
    """在业务包（含界面）里找 `def func_name(` 定义，返回 (文件, 源码)。

    拆分巨兽文件之后，测试仍能按函数名定位到源码，不用关心它在哪个文件。
    找不到返回 (None, "")。
    """
    needle = f"def {func_name}("
    for path in [*pkg_py_files(), *ui_py_files()]:
        text = read(path)
        if needle in text:
            return path, text
    return None, ""


def function_source(func_name: str, next_name: str | None = None) -> str:
    """取某个函数的源码片段（可选的"下一个函数"作为结束边界）。

    这是旧测试里 `src.split("def A(")[1].split("def B(")[0]` 的官方替代，
    区别是它会**跨文件**搜索，所以拆分后依然有效。
    """
    _path, text = find_def(func_name)
    if not text:
        return ""
    body = text.split(f"def {func_name}(", 1)[1]
    if next_name:
        body = body.split(f"def {next_name}(", 1)[0]
    return body


def spec_files():
    """打包 spec（macOS）所在位置。"""
    return sorted((ROOT / "packaging").rglob("*.spec"))

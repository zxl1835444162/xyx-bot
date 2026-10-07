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


def resolve_legacy(rel: str) -> Path:
    """把**重构前的相对路径**解析成现在的真实路径。

    旧测试/旧注释里到处是 `src/ai.py`、`ui/pages/ai_flow.py` 这种写法
    （那时业务包叫 `src`、界面是平级的 `ui`）。有了这个函数，测试照旧写老路径
    也能读到文件，改名的成本就从"18 处调用点"降到"这一处映射"。
    """
    rel = str(rel).replace("\\", "/")
    if rel.startswith("./"):
        rel = rel[2:]
    if rel.startswith("src/"):
        return pkg_file(*rel[len("src/"):].split("/"))
    if rel.startswith("ui/"):
        return ui_file(*rel[len("ui/"):].split("/"))
    return ROOT / rel


def module_source(rel: str) -> str:
    """把一个模块的源码读全。

    * 模块还是单文件 → 返回该文件内容；
    * 模块已经拆成分包（例如 `ai.py` → `ai/`）→ 返回包内所有 .py 的拼接。

    用途：那些"整文件读一遍找关键字"的历史断言（主题色、字体缓存、
    `<Configure>` 守卫的实测数字等）在拆分之后依然能通过，不用改断言。
    """
    p = resolve_legacy(rel)
    if p.is_file():
        return read(p)
    if p.is_dir():
        parts = []
        for f in sorted(p.rglob("*.py")):
            text = read(f)
            # 拼在一起时要丢掉 `from __future__ import ...`：
            # 它必须位于**文件开头**，拼接后会变成语法错误，而对静态检查毫无意义。
            text = "\n".join(
                line for line in text.splitlines()
                if not line.strip().startswith("from __future__ import")
            )
            parts.append(text)
        return "\n".join(parts)
    return ""


def legacy_rel(path) -> str:
    """把真实路径转回**重构前的叫法**（`src/x.py` / `ui/x.py`）。

    resolve_legacy 是"旧写法 → 真实路径"，这个是反向的。测试里那些按旧相对路径
    做键和比较的地方（例如 ALLOW_WINDOWS_ONLY 字典、`rel == "ui/theme.py"`）
    靠它继续生效 —— 改了包名也不用重写这些历史断言。
    """
    p = Path(path).resolve()
    for base, prefix in ((UI, "ui"), (PKG, "src")):
        try:
            return f"{prefix}/{p.relative_to(base).as_posix()}"
        except ValueError:
            continue
    try:
        return p.relative_to(ROOT).as_posix()
    except ValueError:
        return p.as_posix()


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
    """业务包 + 界面里所有 .py。

    用集合去重：界面包收进业务包（xyxbot/ui）之后，`pkg_py_files()` 已经包含它，
    不去重会让共用的静态审计把同一批文件跑两遍（断言数量也会虚高）。
    """
    return sorted({*ui_py_files(), *pkg_py_files()})


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

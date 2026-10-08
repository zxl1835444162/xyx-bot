"""回归守卫：`xyxbot/` 里的**每一个相对导入都必须能解析**。

为什么单独写这个用例
--------------------
从单文件 `ai.py` 拆成 `xyxbot/ai/` 子包时，函数体内的**内联相对导入**最容易漏改：

    # 原来在 xyxbot/ai.py 里（`.` = xyxbot）
    from . import login as _L          # → xyxbot.login  ✓

    # 搬进 xyxbot/ai/flows.py 之后（`.` = xyxbot.ai）
    from . import login as _L          # → xyxbot.ai.login  ✗ ModuleNotFoundError

它只在**特定分支**（`prepare=True`）才触发，跑测试根本发现不了 —— 而线上会直接崩。
所以这里把"相对导入能不能解析"做成一条常驻断言：任何一次拆分/搬家漏改，它当场红。

无需 pytest：`python tests/test_imports_resolve.py`
"""
from __future__ import annotations

import ast
import importlib
import importlib.util
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import _support as S  # noqa: E402  文件布局的唯一接口

PASS: list[str] = []
FAIL: list[str] = []


def check(name: str, cond, detail: str = "") -> None:
    if cond:
        PASS.append(name)
        print(f"  [PASS] {name}")
    else:
        FAIL.append(name)
        print(f"  [FAIL] {name}" + (f": {detail}" if detail else ""))


def module_name_of(path: pathlib.Path) -> str:
    """文件 → 模块名（`__init__.py` 算目录名，不含 __init__）。"""
    rel = path.relative_to(ROOT / "xyxbot")
    parts = list(rel.parts)
    if parts[-1] == "__init__.py":
        parts = parts[:-1]
    else:
        parts[-1] = parts[-1][:-3]
    return ".".join(["xyxbot", *parts])


def abs_module(pkg_name: str, node: ast.ImportFrom, is_package: bool) -> str:
    """把相对导入算成绝对模块名（PEP 328 语义）。

    `pkg_name` 对包就是包名本身，对模块是模块名；相对导入先退到所在包。
    """
    parts = pkg_name.split(".")
    if not is_package:
        parts = parts[:-1]                      # 模块文件：先退到所在包
    up = node.level - 1                          # level=1 → 当前包
    if up:
        parts = parts[:-up] if up <= len(parts) else []
    base = ".".join(parts)
    if node.module:
        return f"{base}.{node.module}" if base else node.module
    return base


def parse_file(path: pathlib.Path):
    """读并解析（utf-8-sig 容忍 BOM；解析失败返回 None 由调用方报失败）。"""
    try:
        return ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    except SyntaxError:
        return None


print("=== ① 每个相对导入的模块都能找到 ===")
bad_modules: list[str] = []
checked = 0
for path in sorted((ROOT / "xyxbot").rglob("*.py")):
    pkg_name = module_name_of(path)
    is_pkg = path.name == "__init__.py"
    tree = parse_file(path)
    if tree is None:
        bad_modules.append(f"{path.relative_to(ROOT)} 无法解析（语法错误）")
        continue
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom) or not node.level:
            continue
        checked += 1
        target = abs_module(pkg_name, node, is_pkg)
        try:
            found = importlib.util.find_spec(target) is not None
        except Exception as e:                                    # noqa: BLE001
            found = False
            target = f"{target}（{e}）"
        if not found:
            bad_modules.append(f"{path.relative_to(ROOT)}:{node.lineno} "
                               f"from {'.' * node.level}{node.module or ''} "
                               f"→ {target}")

check(f"扫到 {checked} 处相对导入，全部可解析", not bad_modules,
      "；".join(bad_modules[:5]))

print("\n=== ② `from . import X` 的那个 X 真的存在（子模块，或包里已导出的名字）===")
bad_attrs: list[str] = []
checked2 = 0
for path in sorted((ROOT / "xyxbot").rglob("*.py")):
    pkg_name = module_name_of(path)
    is_pkg = path.name == "__init__.py"
    tree = parse_file(path)
    if tree is None:
        continue                     # ① 里已经报过
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom) or not node.level:
            continue
        if node.module:          # `from .mod import name` 由 ① 负责模块级检查
            continue
        target = abs_module(pkg_name, node, is_pkg)
        checked2 += 1
        try:
            mod = importlib.import_module(target)
        except Exception as e:                                    # noqa: BLE001
            bad_attrs.append(f"{path.relative_to(ROOT)}:{node.lineno} 导入 {target} 失败：{e}")
            continue
        for alias in node.names:
            # `from . import config` 指的是**子模块**，不是包属性 → 先按子模块找
            sub = f"{target}.{alias.name}"
            try:
                is_sub = importlib.util.find_spec(sub) is not None
            except Exception:                                     # noqa: BLE001
                is_sub = False
            if is_sub or hasattr(mod, alias.name):
                continue
            bad_attrs.append(f"{path.relative_to(ROOT)}:{node.lineno} "
                             f"{target} 里既没有子模块也没有名字 {alias.name!r}")

check(f"`from . import X` 的 {checked2} 处目标名都存在", not bad_attrs,
      "；".join(bad_attrs[:5]))

print("\n" + "=" * 60)
print(f"  通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
if FAIL:
    print("  失败列表：")
    for f in FAIL:
        print(f"    - {f}")
print("=" * 60)
sys.exit(1 if FAIL else 0)

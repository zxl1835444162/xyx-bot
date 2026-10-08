"""诊断：找出「被引用但从没定义」的名字（就是 `after_core` 那类 NameError）。

2026-10-07 的 `_matches()` 里 `after_core` 从未定义 —— 只在"回读没对上"这条
路径上才会执行，于是**用户报的那类"根本没选上"场景实际是崩在这里**，
永远走不到本该救场的重试逻辑。静态扫描能把这一类一次性照出来。

这是**诊断脚本**（不进测试套件）：作用域判断难免有误报，先看它报什么，
人工过一遍；真有价值再固化成断言。
"""
from __future__ import annotations

import ast
import builtins
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
BUILTINS = set(dir(builtins))


def module_globals(tree: ast.Module) -> set:
    out = set()
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            out.add(n.name)
        elif isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store):
            out.add(n.id)
        elif isinstance(n, ast.alias):
            out.add((n.asname or n.name).split(".")[0])
        elif isinstance(n, ast.arg):
            out.add(n.arg)
        elif isinstance(n, ast.ExceptHandler) and n.name:
            out.add(n.name)
        elif isinstance(n, ast.Global):
            out.update(n.names)
    return out


def star_imported(tree: ast.Module) -> bool:
    return any(isinstance(n, ast.ImportFrom) and any(a.name == "*" for a in n.names)
               for n in ast.walk(tree))


def scan_file(path: pathlib.Path) -> list:
    src = path.read_text(encoding="utf-8-sig")
    tree = ast.parse(src)
    globs = module_globals(tree)
    if star_imported(tree):
        return []                      # `from x import *` → 无法判断
    bad = []

    def local_bound(node) -> set:
        out = set()
        for n in ast.walk(node):
            if isinstance(n, ast.arg):
                out.add(n.arg)
            elif isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del)):
                out.add(n.id)
            elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                out.add(n.name)
            elif isinstance(n, ast.alias):
                out.add((n.asname or n.name).split(".")[0])
            elif isinstance(n, ast.ExceptHandler) and n.name:
                out.add(n.name)
            elif isinstance(n, ast.Global):
                out.update(n.names)
        return out

    for fn in [n for n in ast.walk(tree)
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
        known = globs | local_bound(fn)
        for n in ast.walk(fn):
            if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load):
                if n.id not in known and n.id not in BUILTINS:
                    bad.append((path, n.lineno, fn.name, n.id))
    return bad


def main() -> int:
    targets = sys.argv[1:] or ["xyxbot"]
    hits = []
    files = 0
    for t in targets:
        base = ROOT / t
        found = [base] if base.is_file() else sorted(base.rglob("*.py"))
        for p in found:
            if "__pycache__" in p.parts:
                continue
            files += 1
            hits.extend(scan_file(p))
    print(f"  扫过 {files} 个文件")
    if not hits:
        print("  ✓ 没有发现「被引用但未定义」的名字")
        return 0
    print(f"  ⚠ 发现 {len(hits)} 处（需人工过一遍，排除误报）：")
    for path, line, fn, name in hits:
        try:
            where = path.relative_to(ROOT)
        except ValueError:                 # 扫的是仓库外的临时文件
            where = path
        print(f"    {where}:{line}  在 {fn}() 里用了未定义的 {name!r}")
    return 1


if __name__ == "__main__":
    sys.exit(main())

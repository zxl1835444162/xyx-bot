# -*- coding: utf-8 -*-
"""审计所有 `wait_until` / `wait_gone` 调用点：首参是不是"需要参数的函数"。

★★ 为什么要有这个工具（2026-10-04 抓到的最严重 bug）
====================================================

`src/waiting.py` 的 `wait_until(cond, ...)` 要求 `cond` 是**无参**可调用对象。
为了健壮性，它会把谓词抛出的异常当成「条件未满足」吞掉 —— 因为 DOM 还没
渲染出来时，谓词里确实可能抛异常。

这个"贴心"设计带来一个**完全静默**的坑：

    def gen_finished(page) -> bool: ...          # 需要参数
    wait_until(gen_finished, timeout=300, ...)   # ✗ 漏了 lambda

`cond()` 每轮都抛 `TypeError: missing 1 required positional argument`，
被吞成"未满足" → **等待必然超时**，而且日志里一个字都不说。

实测代价：这一版把 `wait_generation` 写成上面那样，于是**每章都要干等满
300 秒**才判"生成失败"，而生成其实约 9 秒就完成了。用户反馈的"等待时间
特别长"就是这个。（`open_review_pane` 里同样漏了 page，每章白等 8.5 秒。）

`waiting.py` 现在会在谓词第一次报错时**打印警告**并带上异常类型；
本工具则是在**代码层面**提前把这类错误找出来。

用法：
    .venv312\\Scripts\\python.exe audit_wait_args.py

局限性：只检查"裸名字"谓词（`wait_until(f, ...)`）。像
`wait_until(self._cond, ...)` 这种属性访问形式不做检查。
"""

from __future__ import annotations

import ast
import pathlib
import sys

WAITERS = {"wait_until", "wait_gone"}


def _required_params(node: ast.FunctionDef) -> int:
    """这个函数最少需要几个位置参数才能调用。"""
    a = node.args
    if a.vararg is not None:          # *args → 可以无参调用
        return 0
    total = len(a.posonlyargs) + len(a.args)
    return max(0, total - len(a.defaults))


def _collect(tree: ast.AST):
    """收集 {作用域链: {名字: 函数节点}} 和所有 Call 及其作用域链。"""
    defs: dict[tuple, dict] = {(): {}}
    calls: list[tuple[tuple, ast.Call]] = []

    def walk(node: ast.AST, scope: tuple):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.FunctionDef):
                defs.setdefault(scope, {})[child.name] = child
                new = scope + (child.name,)
                defs.setdefault(new, {})
                walk(child, new)
            elif isinstance(child, ast.ClassDef):
                new = scope + ("<class>" + child.name,)
                defs.setdefault(new, {})
                walk(child, new)
            else:
                walk(child, scope)
                if isinstance(child, ast.Call):
                    calls.append((scope, child))

    walk(tree, ())
    return defs, calls


def _lookup(defs, scope, name):
    for i in range(len(scope), -1, -1):
        d = defs.get(scope[:i], {})
        if name in d:
            return d[name]
    return None


def audit_source(src: str, name: str) -> list[str]:
    """审计一段源码，返回问题描述列表。"""
    try:
        tree = ast.parse(src)
    except SyntaxError as e:
        return [f"{name}: 语法错误 {e}"]

    defs, calls = _collect(tree)
    problems: list[str] = []
    for scope, call in calls:
        fname = None
        if isinstance(call.func, ast.Name):
            fname = call.func.id
        elif isinstance(call.func, ast.Attribute):
            fname = call.func.attr
        if fname not in WAITERS or not call.args:
            continue
        a0 = call.args[0]
        if not isinstance(a0, ast.Name):
            continue                      # lambda / 调用式 / 属性 → 视为 OK
        d = _lookup(defs, scope, a0.id)
        if d is None:
            continue                      # 可能是导入进来的，交给人工确认
        req = _required_params(d)
        if req > 0:
            problems.append(
                f"{name}:{call.lineno}  ★ {fname}({a0.id}, ...) 但 "
                f"{a0.id} 定义在第 {d.lineno} 行、需要 {req} 个参数 "
                f"→ 每轮抛 TypeError → 等待必然超时！"
                f"（应写成 `lambda: {a0.id}(...)`）")
    return problems


def audit_file(path: pathlib.Path) -> list[str]:
    try:
        return audit_source(path.read_text(encoding="utf-8"), path.name)
    except Exception as e:
        return [f"{path.name}: 读取失败 {e}"]


def target_files(root: pathlib.Path) -> list[pathlib.Path]:
    got: set[pathlib.Path] = set()
    for pat in ("src/*.py", "src/**/*.py", "ui/*.py", "ui/**/*.py"):
        got |= {p for p in root.glob(pat) if p.is_file()}
    return sorted(got)


def audit_all(root: pathlib.Path) -> tuple[int, list[str]]:
    files = target_files(root)
    problems: list[str] = []
    for p in files:
        problems += audit_file(p)
    return len(files), problems


def main() -> int:
    # ★ 输出被重定向到文件/管道时 Windows 会用 GBK，下面的 ✓ 会让 print
    #   直接抛 UnicodeEncodeError（实测）。先加固编码。
    try:
        from src.console import enable_utf8

        enable_utf8()
    except Exception:
        pass

    root = pathlib.Path(__file__).resolve().parents[2]  # 仓库根
    n, problems = audit_all(root)
    print(f"审计了 {n} 个文件")
    if problems:
        print(f"\n发现 {len(problems)} 个问题：")
        for x in problems:
            print("  " + x)
        return 1
    print("✓ 没有问题：所有裸名字谓词都是无参可调用的")
    return 0


if __name__ == "__main__":
    sys.exit(main())

# -*- coding: utf-8 -*-
"""回归测试：`<Configure>` 重绘必须有守卫，不能变成渲染风暴。

无需 pytest，直接 `python tests/test_configure_guard.py`。

★★★ 这个文件守的是 macOS 上「点登录后鼠标转圈、主界面永远不出来」的**直接原因**
=================================================================================

真机实测（GitHub 的 macOS runner，`tests/repro_login.py` 带计数器的版本）：

    ★ 停滞：主线程已 10.3 秒没有任何进展
       最后一次进展：MainWindow.__init__ 结束     ← 主窗**已经建好了**
       ★ 计数：Configure=97968  render=98029  create_text=126038

10 秒内 `<Configure>` 触发 **9.8 万次**、重绘 **9.8 万次**（每秒约一万次）。
主线程全耗在这个循环里，**永远回不到事件循环** → `after` 定时器不触发、
窗口不绘制、鼠标一直转圈。同一份代码在 Windows 上全程只有 32 次 Configure。

原因：在 `<Configure>` 回调里 delete + 重建画布内容（或改 Canvas 配置 /
`place_configure` 子控件），会**再触发一次 `<Configure>`**。macOS 的 Tk
每次重绘都会再发一个，于是 Configure → 重绘 → Configure → … 无限循环。

修法就是 `ui/theme.py` 的 `bind_configure()`。本文件保证：
  ① 它确实会「尺寸没变就不重绘」（破循环的核心）
  ② 它有全局每秒重绘上限（兜底，防别的写法再造出循环）
  ③ 重绘抛异常不会把事件循环带走
  ④ **全项目所有 `<Configure>` 绑定都走它**（AST 检查，防止有人写回裸绑定）

★ 这些都是**不依赖 Tk 定时器**的检查 —— 因为 CI 的 macOS runner 不触发
  定时器（没有真实窗口会话），只能靠这类检查守住。
"""
from __future__ import annotations

import ast
import os
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import _support as S  # noqa: E402  文件布局的唯一接口（见 tests/_support.py）

try:
    from xyxbot.console import enable_utf8

    enable_utf8()
except Exception:
    pass

PASS: list[str] = []
FAIL: list[str] = []


def check(name: str, got, want):
    if got == want:
        PASS.append(name)
        print(f"  [PASS] {name}")
    else:
        FAIL.append(name)
        print(f"  [FAIL] {name}: got={got!r} want={want!r}")


def check_true(name: str, cond, detail: str = ""):
    check(name, bool(cond), True)
    if not cond and detail:
        print(f"         {detail}")


# ==================================================== ① 静态：AST 检查绑定
print("=== ① 静态检查：所有 <Configure> 绑定都必须走 bind_configure ===")
UI_FILES = S.ui_py_files()


def _enclosing_func(tree, lineno: int) -> str:
    """找出 lineno 所在的函数名（最内层）。找不到返回 ""。"""
    best = ("", -1)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.lineno <= lineno <= (getattr(node, "end_lineno", node.lineno)
                                         or node.lineno):
                if node.lineno > best[1]:
                    best = (node.name, node.lineno)
    return best[0]


# ★★ 2026-10-04 收紧：以前这里按「文件」整文件放行 theme.py，理由是
#    「Card.body 内部已有 != 判断」—— **但那个理由是假的**：
#    `_resize_win` 里 `self.configure(height=need)` 并没有 != 判断，
#    于是在 macOS 上照样自激（body Configure → _resize_win →
#    self.configure(height) → self Configure → _redraw → …）。
#    现在改成**按函数**放行：只允许 `bind_configure` 自己内部那一处
#    （它就是守卫实现本身），其它任何裸绑都算失败。
raw_binds = []          # (rel, lineno, func_name)
for p in UI_FILES:
    rel = S.legacy_rel(p)
    try:
        tree = ast.parse(p.read_text(encoding="utf-8"))
    except SyntaxError:
        continue
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "bind"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and node.args[0].value == "<Configure>"):
            raw_binds.append((rel, node.lineno, _enclosing_func(tree, node.lineno)))

outside = [f"{rel}:{ln}({fn})" for rel, ln, fn in raw_binds
           if not (rel.startswith("ui/theme") and fn == "bind_configure")]
check(f"★ 全 ui/ 只有 bind_configure 内部一处裸绑（其余都走守卫）"
      f"（{outside}）", len(outside), 0)
_allowed = [f"{rel}:{ln}({fn})" for rel, ln, fn in raw_binds
            if f"{rel}:{ln}({fn})" not in outside]
print(f"         （允许的裸绑：{_allowed}）")

# 守卫函数的调用点（含 Card.body 这个曾经的漏网点）
_calls = sum(p.read_text(encoding="utf-8").count("bind_configure(")
             for p in UI_FILES)
check_true(f"bind_configure 被真正用起来了（{_calls} 处引用/定义）", _calls >= 8)

# ★★ 断掉自激的核心：写自身尺寸的地方必须有「值没变就不写」的判断
_src = S.module_source("ui/theme.py")
check_true("Card._resize_win 里 self.configure(height) 带 != 判断",
           "self.winfo_reqheight() != need" in _src)

# ==================================================== ② 速率闸门
print("\n=== ② 全局每秒重绘上限（兜底，不依赖 Tk） ===")
from xyxbot.ui import theme  # noqa: E402

check_true("存在 _REDRAW_PER_SEC 上限", isinstance(theme._REDRAW_PER_SEC, int)
           and theme._REDRAW_PER_SEC > 0)
# 重置并连打：超过上限后必须返回 False
theme._REDRAW_BUDGET["t0"] = time.time()
theme._REDRAW_BUDGET["n"] = 0
res = [theme._redraw_allowed() for _ in range(theme._REDRAW_PER_SEC + 5)]
check("前 N 次允许", all(res[:theme._REDRAW_PER_SEC]), True)
check("超过上限后被拒绝", any(not x for x in res[theme._REDRAW_PER_SEC:]), True)
# 跨过 1 秒后恢复
theme._REDRAW_BUDGET["t0"] = time.time() - 2.0
check("下一秒恢复允许", theme._redraw_allowed(), True)

# ==================================================== ③ 行为（不需要窗口）
print("\n=== ③ 行为：尺寸没变就不重绘（核心） ===")
# ★ 不需要真窗口：bind_configure 只用到 bind / after / 属性，
#   用替身做**确定性**验证，比靠事件循环可靠得多（CI 的 macOS runner
#   连 Tk 定时器都不触发）。
from xyxbot.ui.theme import bind_configure  # noqa: E402


class _Ev:
    """假的 <Configure> 事件。"""

    def __init__(self, w, h):
        self.width, self.height = w, h


class _FakeWidget:
    """最小替身：只需要 bind / after / 属性。"""

    def __init__(self):
        self.bound = {}
        self.after_calls = []
        self._cfg_last = None

    def bind(self, seq, func):
        self.bound[seq] = func

    def after(self, ms, func=None, *a):
        self.after_calls.append((ms, func))
        return "id"


fake = _FakeWidget()
hits = {"n": 0}
bind_configure(fake, lambda: hits.__setitem__("n", hits["n"] + 1))
cb = fake.bound["<Configure>"]

cb(_Ev(100, 40))
check("第一次 Configure（尺寸变化）→ 重绘 1 次", hits["n"], 1)
for _ in range(50):
    cb(_Ev(100, 40))
check("再来 50 次**同尺寸** Configure → 仍然只重绘 1 次（★ 破循环）",
      hits["n"], 1)
cb(_Ev(120, 40))
check("尺寸变了 → 再重绘一次", hits["n"], 2)
for _ in range(50):
    cb(_Ev(120, 40))
check("新尺寸下重复同样不重绘", hits["n"], 2)

# ==================================================== ④ 超预算时合并延时重绘
print("\n=== ④ 超预算时合并成一次延时重绘，不丢最终状态 ===")
fake2 = _FakeWidget()
hits2 = {"n": 0}
bind_configure(fake2, lambda: hits2.__setitem__("n", hits2["n"] + 1))
cb2 = fake2.bound["<Configure>"]
theme._REDRAW_BUDGET["t0"] = time.time()
theme._REDRAW_BUDGET["n"] = theme._REDRAW_PER_SEC + 100     # 先把预算打爆
cb2(_Ev(10, 10))                     # 尺寸变了，但预算不足 → 应排定延时重绘
check("超预算时不立即重绘", hits2["n"], 0)
check("但排定了一次延时重绘（保证最终画对）", len(fake2.after_calls), 1)
check("延时重绘的间隔合理（毫秒）", fake2.after_calls[0][0] > 0, True)
# 模拟延时回调执行
fake2.after_calls[0][1]()
check("延时重绘执行后画上了", hits2["n"], 1)

# ==================================================== ⑤ 重绘异常不能带走事件循环
print("\n=== ⑤ 重绘抛异常不能把事件循环带走 ===")
fake3 = _FakeWidget()


def _boom():
    raise RuntimeError("模拟重绘出错")


bind_configure(fake3, _boom)
cb3 = fake3.bound["<Configure>"]
try:
    cb3(_Ev(5, 5))
    check_true("重绘异常被吞掉（不冒泡到 Tk）", True)
except Exception as e:
    check_true(f"重绘异常被吞掉（不冒泡到 Tk），实际抛出 {e!r}", False)

# ==================================================== ⑥ 源码里写明原因
print("\n=== ⑥ 源码里必须写明这是为什么 ===")
_src = S.module_source("ui/theme.py")
check_true("writeup 里有真机实测数据（97968 / 126038）",
           "97968" in _src and "126038" in _src)
check_true("说明了 macOS 特有的行为", "macOS" in _src)
check_true("说明了为什么直接 bind 会死循环",
           "再触发一次" in _src or "无限循环" in _src)

print("\n" + "=" * 64)
print(f"  通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
if FAIL:
    print("  失败列表：")
    for f in FAIL:
        print(f"    - {f}")
print("=" * 64)

sys.stdout.flush()
sys.stderr.flush()
os._exit(1 if FAIL else 0)

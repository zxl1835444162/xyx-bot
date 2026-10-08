"""回归守卫：`xyxbot/` 里不允许出现「被引用但从没定义」的名字。

为什么单独立一条
----------------
2026-10-07 在 `ai/shortcuts.py` 里挖出一个真 bug：

    def _matches(after):
        ...
        if want and (want == after or want_core == after_core):   # after_core 从没定义过

它只在**"回读没对上"这条路径**上执行 —— 也就是用户 2026-10-05 报的
「点击后有时候根本没选上」那个场景。结果是：本该打印告警并**重试点击**的代码
永远不会被执行，而是以 `NameError` 崩掉。跑测试看不见（不在正常路径上），
真机上表现为"偶发失败"。

这类 bug 的特征是：**静态可判、运行时才炸、只在特定分支**。所以做成两条断言：
  ① 全包扫描：任何"引用但未定义"的名字都算失败；
  ② 自检（灵敏度）：故意造一个未定义引用，扫描器**必须**报出来 ——
     否则这道守卫哪天悄悄失效了也没人知道。

无需 pytest：`python tests/test_undefined_names.py`
"""
from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import _support as S  # noqa: E402  文件布局的唯一接口

S.add_tools_to_path()                      # tools/audit/undefined_names.py
import undefined_names as UN                # noqa: E402

PASS: list[str] = []
FAIL: list[str] = []


def check(name: str, cond, detail: str = "") -> None:
    if cond:
        PASS.append(name)
        print(f"  [PASS] {name}")
    else:
        FAIL.append(name)
        print(f"  [FAIL] {name}" + (f": {detail}" if detail else ""))


def scan_tree() -> list:
    hits = []
    for p in sorted((ROOT / "xyxbot").rglob("*.py")):
        if "__pycache__" in p.parts:
            continue
        hits.extend(UN.scan_file(p))
    return hits


print("=== ① 全包扫描：没有「被引用但未定义」的名字 ===")
hits = scan_tree()
detail = "；".join(f"{p.relative_to(ROOT)}:{ln} 在 {fn}() 里用了 {nm!r}"
                   for p, ln, fn, nm in hits[:5])
check(f"xyxbot/ 全部文件静态可判（扫到 {len(list((ROOT/'xyxbot').rglob('*.py')))} 个文件）",
      not hits, detail)

print("\n=== ② 自检：这道守卫真的会响（故意造一个未定义引用）===")
probe_dir = ROOT / "artifacts" / "tmp"
probe_dir.mkdir(parents=True, exist_ok=True)
bad = probe_dir / "_undefined_probe.py"
good = probe_dir / "_defined_probe.py"
bad.write_text("def f(x):\n    return x + never_defined_anywhere\n",
               encoding="utf-8", newline="\n")
good.write_text("def f(x):\n    y = 1\n    return x + y\n",
                encoding="utf-8", newline="\n")
try:
    bad_hits = UN.scan_file(bad)
    good_hits = UN.scan_file(good)
    check("未定义引用会被报出来", len(bad_hits) == 1
          and bad_hits[0][3] == "never_defined_anywhere",
          f"got={bad_hits}")
    check("正常代码不会被误报", not good_hits, f"got={good_hits}")
finally:
    bad.unlink(missing_ok=True)
    good.unlink(missing_ok=True)

print("\n" + "=" * 60)
print(f"  通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
if FAIL:
    print("  失败列表：")
    for f in FAIL:
        print(f"    - {f}")
print("=" * 60)
sys.exit(1 if FAIL else 0)

"""统一测试 runner：`python tests/run_all.py`

**为什么需要它**

以前 CI 里是这么跑的：

    for t in test_fixes test_waiting test_runplan ...; do python "tests/$t.py"; done

测试文件名硬编码在 CI 的 yml 里 —— **新增一个测试很容易忘了加进去**，
于是"测试全绿"这句话本身就不完整。这个 runner 自己发现 `tests/test_*.py`，
CI 只调它一个命令，再也不会漏。

**怎么判定通过**

每个测试脚本都会打印一行 `通过 N 项，失败 M 项`，runner 解析它，
再结合进程退出码；两者都 OK 才算过。测试自己超时会被杀掉并标记 TIMEOUT
（比让 CI job 挂到 6 小时上限强）。

**用法**

    python tests/run_all.py                # 全部（GUI 用例在无窗口时会自跳过）
    python tests/run_all.py --list         # 只列出会被跑到的用例
    python tests/run_all.py --only test_fixes,test_waiting
    python tests/run_all.py --quick        # 跳过 GUI/启动/全功能这三个慢用例
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / "tests"
LOGDIR = ROOT / "artifacts" / "logs" / "tests"

#: 需要窗口/事件循环的慢用例（无图形会话时它们会自己 SKIP，不是失败）
GUI_TESTS = {"test_gui_pages", "test_startup", "test_all_features_macos"}

PER_TEST_TIMEOUT = 300  # 秒
SUMMARY_RE = re.compile(r"通过\s*(\d+)\s*项[，,]?\s*失败\s*(\d+)\s*项")

#: 测试运行时统一注入的环境变量
BASE_ENV = {
    "PYTHONUTF8": "1",          # 输出里全是中文和 ⚠/★，别让 GBK 把它打成异常
    "XYX_NO_DIALOG": "1",       # messagebox 是模态的，CI/无人值守会挂死
    "XYX_HANG_SECONDS": "20",   # 启动回归的看门狗
    "XYX_PUMP_SECONDS": "10",
    "XYX_FEATURE_PUMP": "5",
}


def discover(quick: bool = False) -> list[Path]:
    files = sorted(TESTS.glob("test_*.py"))
    if quick:
        files = [f for f in files if f.stem not in GUI_TESTS]
    return files


def run_one(path: Path) -> dict:
    env = dict(os.environ)
    env.update(BASE_ENV)
    started = time.time()
    try:
        proc = subprocess.run(
            [sys.executable, str(path)],
            capture_output=True, timeout=PER_TEST_TIMEOUT, env=env, cwd=str(ROOT),
        )
        out = (proc.stdout or b"").decode("utf-8", "replace")
        err = (proc.stderr or b"").decode("utf-8", "replace")
        code = proc.returncode
        note = ""
    except subprocess.TimeoutExpired as exc:
        out = (exc.stdout or b"").decode("utf-8", "replace") if exc.stdout else ""
        err = (exc.stderr or b"").decode("utf-8", "replace") if exc.stderr else ""
        code = -9
        note = f"TIMEOUT（超过 {PER_TEST_TIMEOUT}s 被终止）"

    took = time.time() - started
    m = SUMMARY_RE.search(out)
    passed = int(m.group(1)) if m else 0
    failed = int(m.group(2)) if m else -1        # -1：连汇总行都没打出来
    ok = code == 0 and failed == 0

    LOGDIR.mkdir(parents=True, exist_ok=True)
    (LOGDIR / f"{path.stem}.log").write_text(
        f"$ python {path.name}\nexit={code}\n\n===== stdout =====\n{out}\n===== stderr =====\n{err}",
        encoding="utf-8",
    )
    return {
        "name": path.stem, "rc": code, "passed": passed, "failed": failed,
        "seconds": took, "ok": ok, "note": note,
        "skipped": "SKIP" in out or "跳过" in out,
        "err_tail": "\n".join(err.strip().splitlines()[-3:]),
    }


def main() -> int:
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("--list", action="store_true", help="只列出用例")
    ap.add_argument("--only", default="", help="只跑这些用例（逗号分隔）")
    ap.add_argument("--quick", action="store_true", help="跳过需要窗口的慢用例")
    args = ap.parse_args()

    files = discover(args.quick)
    if args.only:
        wanted = {x.strip() for x in args.only.split(",") if x.strip()}
        files = [f for f in files if f.stem in wanted]

    if args.list:
        for f in files:
            tag = "GUI" if f.stem in GUI_TESTS else "   "
            print(f"{tag} {f.stem}")
        return 0

    if not files:
        print("没有找到任何测试。")
        return 1

    print("=" * 68)
    print(f"  统一测试 runner · {len(files)} 个用例 · 日志 {LOGDIR}")
    print("=" * 68)

    results = []
    for f in files:
        r = run_one(f)
        results.append(r)
        flag = "✓" if r["ok"] else ("✗" if r["failed"] != 0 else "✗")
        tail = f"  {r['note']}" if r["note"] else ""
        skipped = "  (含 SKIP)" if r["skipped"] and r["ok"] else ""
        print(f"  {flag} {r['name']:<26} 通过 {r['passed']:<4} 失败 "
              f"{r['failed'] if r['failed'] >= 0 else '?':<3} {r['seconds']:5.1f}s"
              f"{skipped}{tail}")
        if not r["ok"] and r["err_tail"]:
            for line in r["err_tail"].splitlines():
                print(f"       | {line}")

    total_passed = sum(r["passed"] for r in results)
    bad = [r for r in results if not r["ok"]]
    print("=" * 68)
    print(f"  合计断言 {total_passed} 项 · 用例 {len(results) - len(bad)}/{len(results)} 通过")
    if bad:
        print(f"  失败用例：{', '.join(r['name'] for r in bad)}")
        print(f"  详细日志：{LOGDIR}")
        return 1
    print("  全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())

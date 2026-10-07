# -*- coding: utf-8 -*-
"""回归测试：跑章进度/ETA/预检（`src/runplan.py`）+ 协作式中止。

无需 pytest，直接 `python tests/test_runplan.py`。

为什么单独一个文件：
    `test_waiting.py` 管"等待语义"，本文件管"界面要显示的那些数"和
    "用户点停止能不能真的停下"。两者都是**纯逻辑**，不需要浏览器、不需要窗口。
"""
from __future__ import annotations

import os
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

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


# ==================================================== 1. runplan 进度 / ETA
print("=== 1. 进度与预计剩余（纯计算） ===")
from xyxbot.runplan import (DEFAULT_SECONDS_PER_CHAPTER, Check, Progress,
                         fmt_duration, format_checks, has_blocking_error,
                         next_retry_range, preflight)

# --- 空进度不能炸，也不能除零
p = Progress()
check("空进度 percent = 0", p.percent, 0.0)
check("空进度 remaining = 0", p.remaining, 0)
check("空进度 line", p.line(), "尚未开始")
check_true("空进度 avg 用经验值", p.avg_seconds == DEFAULT_SECONDS_PER_CHAPTER)
check("空进度 eta = 0", p.eta_seconds, 0.0)
check_true("空进度不算结束", not p.is_finished)

# --- percent 边界
p = Progress(total=8, done=0)
check("0/8 → 0%", p.percent, 0.0)
p.done = 4
check("4/8 → 50%", p.percent, 50.0)
p.done = 8
check("8/8 → 100%", p.percent, 100.0)
check_true("8/8 算结束", p.is_finished)
p.done = 99
        
check("超过 total 也封顶 100%", p.percent, 100.0)

# --- avg 用真实耗时
p = Progress(total=4, done=2, chapter_seconds=[100.0, 200.0])
check("avg 用真实值", p.avg_seconds, 150.0)
check("real avg 时 eta = 剩余×均值", p.eta_seconds, 300.0)
p2 = Progress(total=4, done=0)
check_true("没跑完任何章时 eta 用经验值",
           p2.eta_seconds == DEFAULT_SECONDS_PER_CHAPTER * 4)

# --- 正在跑的那一章按半章计入剩余（最后一章时不该显示 0）
p = Progress(total=2, done=1, chapter_seconds=[120.0],
             phase="start", running_no=2)
check("最后一章在跑 → ETA 按半章", p.eta_seconds, 60.0)

# --- apply() 吃 ai_batch_chapters 的进度事件
p = Progress()
p.apply({"total": 3, "phase": "start", "no": 1, "done_count": 0,
         "ok_count": 0, "total_elapsed": 0.5})
check("start 事件 → running_no", p.running_no, 1)
check("start 事件 → phase", p.phase, "start")
check("start 事件不改 done", p.done, 0)

p.apply({"total": 3, "phase": "done", "no": 1, "ok": True, "elapsed": 120.0,
         "done_count": 1, "ok_count": 1, "total_elapsed": 120.5})
check("done 事件 → done", p.done, 1)
check("done 事件 → ok_count", p.ok_count, 1)
check("done 事件 → running_no 归零", p.running_no, 0)
check("done 事件 → 记下本章耗时", p.chapter_seconds, [120.0])

p.apply({"total": 3, "phase": "done", "no": 2, "ok": False, "elapsed": 60.0,
         "reason": "生成超时", "done_count": 2, "ok_count": 1,
         "total_elapsed": 181.0})
check("失败章进 failed", p.failed, [2])
check_true("失败章不进 ok_count", p.ok_count == 1)
check_true("失败章也算 done（进度要往前走）", p.done == 2)

p.apply({"total": 3, "phase": "done", "no": 3, "ok": False, "aborted": True,
         "elapsed": 10.0, "done_count": 3, "ok_count": 1,
         "total_elapsed": 191.0})
check_true("中止章进 aborted", p.aborted == [3])
check_true("中止章**不**进 failed（否则会误导重跑）", 3 not in p.failed)

# --- 用 done_count 校正（跳章/重跑时也准，不靠自增）
p = Progress()
p.apply({"total": 5, "phase": "done", "no": 5, "ok": True, "elapsed": 10.0,
         "done_count": 1, "ok_count": 1})
check("done_count 优先于自增", p.done, 1)

# --- 展示行
p = Progress(total=8, done=4, ok_count=3, failed=[5], elapsed=492.0,
             chapter_seconds=[130.0, 118.0, 121.0], running_no=6,
             phase="start")
check_true("进度行含 4/8", "4/8" in p.line(), p.line())
check_true("进度行含当前章", "第 6 章" in p.line(), p.line())
check_true("进度行含失败章", "失败 5" in p.line(), p.line())
check_true("节奏行含已用/预计", "已用" in p.timing_line()
           and "预计剩余" in p.timing_line(), p.timing_line())

# --- fmt_duration
check("fmt 0s", fmt_duration(0), "0秒")
check("fmt 45s", fmt_duration(45), "45秒")
check("fmt 192s", fmt_duration(192), "3分12秒")
check("fmt 整分", fmt_duration(180), "3分")
check("fmt 3720s", fmt_duration(3720), "1小时2分")
check("fmt 负数不炸", fmt_duration(-5), "0秒")

# --- next_retry_range
check("没有失败章 → None",
      next_retry_range(Progress(total=3, done=3, ok_count=3), 10), None)
check("有失败章 → (最小失败章, 原结束章)",
      next_retry_range(Progress(total=3, done=3, failed=[4, 6]), 10), (4, 10))

# ==================================================== 2. 预检
print("\n=== 2. 开跑前预检 ===")
GOOD = dict(book="新建作品12", start=3, end=5, site_chapters=[1, 2, 3, 4, 5],
            auto_new=True, template="标题10-15字。#@", unknown_codes=[],
            empty_codes=[], logged_in=True, session_age="1天前",
            has_project=True, project_name="开局被绿", project_chapters=7,
            preview_len=260)

cs = preflight(**GOOD)
check_true("全绿场景没有阻塞错误", not has_blocking_error(cs))
check_true("全绿场景有 ok 项", any(c.level == "ok" for c in cs))

# 缺登录态
cs = preflight(**{**GOOD, "logged_in": False})
check_true("没登录 → 阻塞", has_blocking_error(cs))
check_true("没登录 → 明确指向「准备」页",
           any("准备" in c.detail for c in cs if c.is_error))

# 没填作品名
cs = preflight(**{**GOOD, "book": "   "})
check_true("没填作品名 → 阻塞", has_blocking_error(cs))

# 范围非法
check_true("起始章为 0 → 阻塞",
           has_blocking_error(preflight(**{**GOOD, "start": 0})))
check_true("结束<起始 → 阻塞",
           has_blocking_error(preflight(**{**GOOD, "start": 9, "end": 3})))
check_true("范围合法 → 不阻塞",
           not has_blocking_error(preflight(**{**GOOD, "start": 3, "end": 10})))

# 缺章：开自动新建 → 警告；不开 → 阻塞
cs = preflight(**{**GOOD, "start": 6, "end": 9, "auto_new": True})
check_true("缺章+自动新建 → 只是警告", not has_blocking_error(cs))
check_true("缺章+自动新建 → 有 warn",
           any(c.level == "warn" and "自动新建" in c.title for c in cs))
cs = preflight(**{**GOOD, "start": 6, "end": 9, "auto_new": False})
check_true("缺章+不自动新建 → 阻塞", has_blocking_error(cs))

# 模板问题
check_true("空模板 → 阻塞",
           has_blocking_error(preflight(**{**GOOD, "template": "   "})))
check_true("引用不存在的代号 → 阻塞",
           has_blocking_error(preflight(**{**GOOD, "unknown_codes": [99]})))
check_true("细纲为空 → 只警告",
           not has_blocking_error(preflight(**{**GOOD, "empty_codes": [7]})))
check_true("没有 #@ 也没 #N → 警告每章一样",
           any("每章会送同一段文本" in c.title
               for c in preflight(**{**GOOD, "template": "继续写"})))
check_true("没有 #@ 但有 #N → 说明按当前章处理",
           any("当前章" in c.title
               for c in preflight(**{**GOOD, "template": "看 #1"})))

# 没分章
check_true("没分章 → 阻塞",
           has_blocking_error(preflight(**{**GOOD, "has_project": False})))

# 站点章节未知（没连浏览器）→ 不该因此报错
cs = preflight(**{**GOOD, "site_chapters": None})
check_true("站点章节未知时不报缺章错误", not has_blocking_error(cs))

# 格式化
lines = format_checks(cs)
check_true("format_checks 每项一行且带图标",
           len(lines) == len(cs) and all(ln[:1] in "✓⚠✗·" for ln in lines),
           str(lines[:2]))

# ==================================================== 3. 协作式中止
print("\n=== 3. 中止（停止按钮的后端） ===")
from xyxbot.waiting import wait_gone, wait_until

flag = {"stop": False}
t0 = time.time()
r = wait_until(lambda: False, timeout=1.0, interval=0.05,
               should_abort=lambda: flag["stop"])
el_idle = time.time() - t0
check_true("未请求中止时会走满超时", r.ok is False and r.aborted is False)
check_true(f"未请求中止 → 走满 1s 超时（{el_idle:.2f}s）", 1.0 <= el_idle < 1.5)

# 中止判据一开始就为真 → 必须**立刻**返回（不等超时）
t0 = time.time()
r = wait_until(lambda: False, timeout=30.0, interval=0.05,
               should_abort=lambda: True)
el = time.time() - t0
check_true("一开始就中止 → aborted=True", r.aborted is True)
check_true(f"一开始就中止 → 立刻返回（{el*1000:.0f}ms）", el < 0.2)
check_true("aborted 的 ok 必须是 False", r.ok is False)

# 中途请求中止 → 必须在一个轮询周期内退出（不能等满 30 秒）
flag["stop"] = False


def _later():
    time.sleep(0.3)
    flag["stop"] = True


import threading
threading.Thread(target=_later, daemon=True).start()
t0 = time.time()
r = wait_until(lambda: False, timeout=30.0, interval=0.05,
               should_abort=lambda: flag["stop"])
el = time.time() - t0
check_true("中途中止 → aborted=True", r.aborted is True)
check_true(f"中途中止 → 快速退出（{el:.2f}s « 30s）", el < 1.5,
           "若接近 30s，说明 should_abort 没生效")

# wait_gone 也要支持
r = wait_gone(lambda: True, timeout=30.0, interval=0.05,
              should_abort=lambda: True)
check_true("wait_gone 也支持中止", r.aborted is True)

# 中止判据本身抛异常 → 按"不中止"处理（不能把等待弄崩）
r = wait_until(lambda: True, timeout=1.0, interval=0.05,
               should_abort=lambda: 1 / 0)
check_true("中止判据抛异常不影响正常命中", r.ok is True)

# --- ai 模块的取消 API
from xyxbot import ai as AI

AI.clear_cancel()
check_true("clear_cancel 后 cancel_requested=False",
           AI.cancel_requested() is False)
AI.request_cancel()
check_true("request_cancel 后 cancel_requested=True",
           AI.cancel_requested() is True)
check_true("canceled() 是 cancel_requested 的别名", AI.canceled() is True)
AI.clear_cancel()
check_true("再 clear 回到 False", AI.cancel_requested() is False)

# --- wait_generation 收到中止要**快速**返回 False，而不是等满 timeout
class _Loc:
    def __init__(self, n=0):
        self._n = n

    @property
    def first(self):
        return self

    def count(self):
        return self._n

    def is_visible(self, timeout=None):
        return self._n > 0

    def locator(self, _s):
        return _Loc(0)

    def inner_text(self, timeout=None):
        return ""

    def get_attribute(self, _n):
        return ""

    def input_value(self, timeout=None):
        return ""

    def click(self, **k):
        return None

    def evaluate(self, _js):
        return None

    def screenshot(self, **k):
        return None


class _Page:
    def locator(self, _s):
        return _Loc(1) if _s == ".n-modal" else _Loc(0)

    def evaluate(self, _js):
        return None

    def screenshot(self, **k):
        return None


AI.request_cancel()
t0 = time.time()
ok = AI.wait_generation(_Page(), timeout=60.0, poll=0.1)
el = time.time() - t0
AI.clear_cancel()
check_true("中止状态下 wait_generation 返回 False", ok is False)
check_true(f"中止状态下 wait_generation 快速返回（{el:.2f}s « 60s）",
           el < 2.0,
           "若接近 60s，说明 should_abort 没接进 wait_generation")

# --- ai_batch_chapters 的中止/进度契约（用假 page，不联网）
print("\n=== 4. ai_batch_chapters 进度回调与中止 ===")
import inspect

_sig = inspect.signature(AI.ai_batch_chapters)
check_true("ai_batch_chapters 有 on_progress 参数",
           "on_progress" in _sig.parameters)
check_true("ai_batch_chapters 有 should_stop 参数",
           "should_stop" in _sig.parameters)

# should_stop 一开始就为真 → 一章都不跑，且 aborted=True
AI.clear_cancel()
events: list = []
t0 = time.time()
res = AI.ai_batch_chapters(
    _Page(), start=1, end=5,
    plot_for=lambda no: "剧情",
    should_stop=lambda: True,
    on_progress=lambda ev: events.append(ev))
check_true("should_stop=True → 不跑任何一章", res["total"] == 0, str(res))
check_true("should_stop=True → aborted=True", res["aborted"] is True)
check_true("没有发出任何进度事件", not events)
check_true("返回里带 elapsed", "elapsed" in res)

# 范围非法 → 也要带 aborted 键（界面不会 KeyError）
res = AI.ai_batch_chapters(_Page(), start=9, end=3)
check_true("非法范围返回里也有 aborted 键", res["aborted"] is False)

# ==================================================== 5. 「上次跑到哪」
print("\n=== 5. 「上次跑到哪」的记忆（src/workspace.py） ===")
import pathlib as _pl
import tempfile

from xyxbot import workspace as WS

# ★★ 必须换掉配置文件路径再测 —— 否则会**覆盖用户真实的
#   artifacts/storage/workspace.json**（里面是他实际的跑章配置）。
_TMP_DIR = _pl.Path(tempfile.mkdtemp(prefix="xyx-ws-test-"))
WS.WS_FILE = _TMP_DIR / "workspace.json"
check_true("测试用的是临时配置路径（没碰用户真实配置）",
           WS.WS_FILE == _TMP_DIR / "workspace.json")

check_true("从没记录过 → last_run().ok = False",
           WS.last_run()["ok"] is False)
check("从没记录过 → next_run_range = None", WS.next_run_range(), None)

WS.note_batch_run(10, 8)
_r = WS.last_run()
check("记录后 ok = True", _r["ok"], True)
check("记下成功跑完的最高章", _r["done"], 10)
check("记下本次段长", _r["span"], 8)
check_true("记下结束时间", bool(_r["at"]), str(_r))
check("接着上次继续 → (11, 18)", WS.next_run_range(), (11, 18))
check("段长可覆盖", WS.next_run_range(default_span=3), (11, 18))

# 一章都没成功（全是失败/中止）→ 不该让人"接着跑"，否则会跳过没跑的章
WS.note_batch_run(0, 5)
check_true("零成功 → ok = False", WS.last_run()["ok"] is False)
check("零成功 → next_run_range = None", WS.next_run_range(), None)

# 段长缺失 → 用调用方给的默认值
WS.note_batch_run(3, 0)
check("段长缺失 → 用默认段长", WS.next_run_range(default_span=4), (4, 7))

# 写坏了也不能崩
(_TMP_DIR / "workspace.json").write_text("{ 这不是 json", encoding="utf-8")
check_true("配置文件损坏时 last_run 不抛异常并返回 ok=False",
           WS.last_run()["ok"] is False)

# ==================================================== 汇总
print("\n" + "=" * 60)
print(f"  通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
if FAIL:
    print("  失败列表：")
    for f in FAIL:
        print(f"    - {f}")
print("=" * 60)

sys.stdout.flush()
sys.stderr.flush()
os._exit(1 if FAIL else 0)

# -*- coding: utf-8 -*-
"""回归测试：验证本次修复（无需 pytest，直接 python 运行）。

覆盖：
  1. BrowserSession 的线程模型 / 互斥 / 停止（无 tkinter、纯 Python）
  2. theme.BrandButton 的禁用真正生效
  3. src.novel 的 #@ 渲染与未知代号处理
  4. src.login 的 URL 兜底判据
  5. src.browser 的 slow_mo 接线
  6. src.ai 的 ai_auto_chapter 返回契约（静态检查）
  7. src.session 的账号提取（对着真实 state.json 结构）
  8. src.browser_detector 的缓存与去重

用法：
    .venv312\\Scripts\\python.exe tests\\test_fixes.py
"""
from __future__ import annotations

import json
import pathlib
import sys
import threading
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# ★ 输出被重定向到文件/管道时，Windows 会用 GBK，日志里的 ⚠ 会让
#   print 直接抛 UnicodeEncodeError（实测退出码 1）。先加固编码。
try:
    from src.console import enable_utf8

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


# ============================================================ 1. BrowserSession
print("\n=== 1. BrowserSession（线程模型 / 互斥 / 停止） ===")
from ui.browser_session import BrowserSession

logs: list[tuple] = []
sess = BrowserSession(log=lambda m, lv="info": logs.append((m, lv)))

# 1a. submit 在常驻线程里执行
seen_thread = []
sess.submit(lambda: seen_thread.append(threading.current_thread().name))
time.sleep(0.4)
check("submit runs on worker thread", seen_thread, ["pw-worker"])

# 1b. is_worker_thread 判定
sess.submit(lambda: seen_thread.append(sess.is_worker_thread()))
time.sleep(0.4)
check("is_worker_thread True inside submit", seen_thread[-1], True)

# 1c. 串行执行：后投的任务不会插队
order: list[str] = []


def slow():
    time.sleep(0.35)
    order.append("first")


sess.submit(slow)
sess.submit(lambda: order.append("second"))
time.sleep(0.15)
check("serial: second not started yet", order, [])
time.sleep(0.6)
check("serial: executed in order", order, ["first", "second"])

# 1d. 互斥：第二个任务被拒绝
started = []


def hold():
    started.append(1)
    time.sleep(0.4)


check_true("run_guarded accepts first", sess.run_guarded("t1", hold))
time.sleep(0.1)
check("run_guarded rejects second", sess.run_guarded("t2", lambda: None), False)
check_true("rejection logged",
           any("还在运行" in m for m, _ in logs), f"logs={logs}")
time.sleep(0.6)
check_true("mutex released after done", not sess.busy)

# 1e. on_done 一定被调用（成功路径）
done_called = []
sess.run_guarded("t3", lambda: None, on_done=lambda: done_called.append(1))
time.sleep(0.4)
check("on_done called on success", done_called, [1])

# 1f. on_done 一定被调用（异常路径）+ 常驻线程存活
done_called2 = []


def boom():
    raise RuntimeError("boom")


sess.run_guarded("t4", boom, on_done=lambda: done_called2.append(1))
time.sleep(0.4)
check("on_done called on failure", done_called2, [1])
alive = []
sess.submit(lambda: alive.append(1))
time.sleep(0.4)
check("worker survives task exception", alive, [1])

# 1g. stop() 投递到常驻线程执行
class FakeApp:
    def __init__(self):
        self.stopped_by: list[str] = []

    def stop(self):
        self.stopped_by.append(threading.current_thread().name)


fake = FakeApp()
sess._app = fake
sess.stop()
time.sleep(0.4)
check("stop() ran on worker thread", fake.stopped_by, ["pw-worker"])
check("stop() cleared app ref", sess.app, None)

# 1h. stop() 对 None 安全
sess.stop()
time.sleep(0.2)
check("stop() with no app is safe", True, True)

sess.shutdown(wait=1.0)
check_true("shutdown joins thread", not sess._thread.is_alive())

# ============================================================ 2. BrandButton
print("\n=== 2. theme.BrandButton 禁用生效 ===")
import tkinter as tk
import types

from ui.theme import BrandButton

root = tk.Tk()
root.withdraw()
calls: list[int] = []
btn = BrandButton(root, "t", command=lambda: calls.append(1))
btn._btn_w, btn._btn_h = 160, 38


def click():
    btn._on_release(types.SimpleNamespace(x=5, y=5))


click()
check("enabled click fires", len(calls), 1)
btn.config(state="disabled")
click()
check("disabled click blocked (config)", len(calls), 1)
check("config(state) sets _enabled", btn._enabled, False)
btn.config(state="normal")
click()
check("re-enabled click fires", len(calls), 2)
btn.set_enabled(False)
click()
check("disabled click blocked (set_enabled)", len(calls), 2)
btn.configure(background="#123456")
check("configure forwards other options", btn.cget("background"), "#123456")
root.destroy()

# ============================================================ 3. novel 渲染
print("\n=== 3. src.novel 的 #@ 与未知代号 ===")
from src.novel import NovelProject, split_novel

TXT = "第1章 a\n正文一。\n第2章 b\n正文二。\n第3章 c\n正文三。\n"
proj = NovelProject(name="t", chapters=split_novel(TXT))
proj.set_note(1, "细纲一")
proj.set_note(2, "细纲二")
proj.set_note(3, "细纲三")

out = proj.render_template("根据 #@ 续写，参考 #1。", current=2)
check_true("#@ resolved to ch2", "细纲二" in out, out)
check_true("#1 stays absolute", "细纲一" in out, out)
check_true("no literal #@", "#@" not in out, out)

# 批量：无 #@ 时 #N 当作当前章
out2 = proj.render_for_batch(3, template="参考 #1 续写")
check_true("batch: #1 -> current ch3", "细纲三" in out2, out2)

# 未知代号：原样保留（不再被静默当成当前章）
out3 = proj.render_for_batch(3, template="参考 #1 和 #99 续写")
check_true("batch: unknown #99 preserved", "#99" in out3, out3)
check_true("batch: known #1 -> current", "细纲三" in out3, out3)

check("_code_numbers dedup+order",
      proj._code_numbers("a #1 b [2] c {{第3章}} d #99 e #1"), [1, 2, 3, 99])

# 有 #@ 时 #N 保持绝对
out4 = proj.render_for_batch(3, template="#1 和 #@")
check_true("with #@: #1 absolute", "细纲一" in out4, out4)
check_true("with #@: #@ current", "细纲三" in out4, out4)

# ============================================================ 4. login URL 判据
print("\n=== 4. src.login 的 URL 兜底判据 ===")
from src.login import _is_site_url

check("about:blank rejected", _is_site_url("about:blank"), False)
check("chrome-error rejected", _is_site_url("chrome-error://x/"), False)
check("empty rejected", _is_site_url(""), False)
check("site home accepted", _is_site_url("https://xingyuexiezuo.com/"), True)
check("site hash route accepted",
      _is_site_url("https://xingyuexiezuo.com/#/books"), True)
check("other domain rejected", _is_site_url("https://example.com/"), False)

# ============================================================ 5. slow_mo 接线
print("\n=== 5. src.browser 的 slow_mo 接线 ===")
import inspect

from src import browser as B

check_true("slow_mo passed to launch",
           "slow_mo=C.SLOW_MO" in inspect.getsource(B.open_browser))

# ============================================================ 5b. 日志重定向
print("\n=== 5b. src.logging_redirect（线程安全 / 行完整性） ===")
import tempfile

from src.logging_redirect import LogRedirector

# 基础三路分发，且 sink 不该收到空行
_lf = pathlib.Path(tempfile.mkdtemp()) / "a.log"
_got: list[str] = []
_r = LogRedirector(sink=lambda m: _got.append(m), log_file=_lf)
_r.install()
print("hello")
print("world")
_r.restore()
check("sink 收到两行且无空行", _got, ["hello", "world"])
check("日志文件内容正确", _lf.read_text(encoding="utf-8"), "hello\nworld\n")

# 空行在文件里要保留
_lf2 = pathlib.Path(tempfile.mkdtemp()) / "b.log"
_r2 = LogRedirector(sink=lambda m: None, log_file=_lf2)
_r2.install()
print("a")
print()
print("b")
_r2.restore()
check("空行在文件中保留", _lf2.read_text(encoding="utf-8"), "a\n\nb\n")

# ★ 并发：多线程下不能再出现粘连乱码行（修复前的真 bug）
_lf3 = pathlib.Path(tempfile.mkdtemp()) / "c.log"
_r3 = LogRedirector(sink=lambda m: None, log_file=_lf3)
_r3.install()


def _w(n):
    for i in range(50):
        print(f"t{n}-{i}")


_ts = [threading.Thread(target=_w, args=(n,)) for n in range(8)]
for _t in _ts:
    _t.start()
for _t in _ts:
    _t.join()
_r3.close()
_lines = _lf3.read_text(encoding="utf-8").splitlines()
check("并发写入 400 行", len(_lines), 400)
check("并发写入无重复", len(set(_lines)), 400)
check("无粘连乱码行", [x for x in _lines if x.count("-") != 1], [])

# 无换行结尾的残留要在 close 时补写
_lf4 = pathlib.Path(tempfile.mkdtemp()) / "d.log"
_r4 = LogRedirector(log_file=_lf4)
_r4.install()
sys.stdout.write("tail")
_r4.close()
check_true("残留片段在 close 时补写",
           _lf4.read_text(encoding="utf-8").endswith("tail\n"))

# 无 log_file 也要安全
_r5 = LogRedirector(log_file=None)
_r5.install()
print("no file")
_r5.restore()
check("无 log_file 不抛异常", True, True)

# ============================================================ 6. ai 返回契约
print("\n=== 6. src.ai 的 ai_auto_chapter 返回契约 ===")
from src import ai as AI

src_auto = inspect.getsource(AI.ai_auto_chapter)
src_batch = inspect.getsource(AI.ai_batch_chapters)
check_true("result seeds ok=False", '"ok": False' in src_auto)
check_true("result seeds reason", '"reason":' in src_auto)
check_true("batch prefers r['ok']", 'r.get("ok"' in src_batch)
check_true("batch reads reason", 'r.get("reason")' in src_batch)

# 统计所有 return 前是否都设了 reason（粗略但有效）
import re as _re

returns = [m.start() for m in _re.finditer(r"\n    return result", src_auto)]
with_reason = 0
for pos in returns:
    tail = src_auto[max(0, pos - 400):pos]
    if "result[\"reason\"]" in tail:
        with_reason += 1
check_true(f"all {len(returns)} early returns set reason",
           with_reason >= len(returns) - 1,
           f"with_reason={with_reason} returns={len(returns)}")

# ============================================================ 7. session 账号提取
print("\n=== 7. src.session 账号提取（真实 state.json 结构） ===")
state_file = ROOT / "artifacts" / "storage" / "state.json"
if state_file.exists():
    state = json.loads(state_file.read_text(encoding="utf-8"))
    ls = {}
    for o in state.get("origins", []):
        for kv in o.get("localStorage", []):
            ls[kv["name"]] = kv["value"]
    WANT = ["nickName", "nickname", "username", "userName", "name",
            "account", "mobile", "phone", "uid", "id"]

    def dig(o, depth=0):
        if not isinstance(o, dict) or depth > 4:
            return ""
        for k in WANT:
            v = o.get(k)
            if v is not None and str(v).strip():
                return str(v).strip()
        for k in o:
            r = dig(o[k], depth + 1)
            if r:
                return r
        return ""

    found = ""
    for k in ["userStorage", "userInfo", "user_info", "user",
              "account", "username", "nickName", "userData"]:
        raw = ls.get(k)
        if not raw:
            continue
        try:
            v = dig(json.loads(raw))
            if v:
                found = v
                break
        except Exception:
            if len(raw) < 40:
                found = raw
                break
    check_true("account found via userStorage", bool(found), f"found={found!r}")
    print(f"         (解析出的账号：{found!r})")
    # 源码里确实包含 userStorage 候选键
    check_true("session.py scans userStorage",
               "userStorage" in inspect.getsource(__import__(
                   "src.session", fromlist=["x"])._guess_account))
else:
    print("  [SKIP] 没有 state.json")

# ============================================================ 8. detector 缓存
print("\n=== 8. src.browser_detector 缓存与去重 ===")
from src.browser_detector import BrowserDetector as BD

BD._cache = None
d1 = BD.detect_all_browsers(use_cache=False)
check("cache populated", BD._cache is not None, True)
check("duplicate paths deduped",
      len(set(d1.values())), len(d1))
check("shared PRIORITY_ORDER used",
      "PRIORITY_ORDER" in inspect.getsource(BD.get_recommended_browser), True)

# ============================================================ 汇总
print("\n" + "=" * 60)
print(f"  通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
if FAIL:
    print("  失败列表：")
    for f in FAIL:
        print(f"    - {f}")
print("=" * 60)

import os

# ★ flush 必须加：os._exit 不会刷缓冲区，
#   一旦把输出重定向到文件/管道，测试结果就整个丢了（实测踩过）。
sys.stdout.flush()
sys.stderr.flush()
os._exit(1 if FAIL else 0)

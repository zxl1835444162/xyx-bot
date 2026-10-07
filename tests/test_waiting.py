# -*- coding: utf-8 -*-
"""回归测试：条件驱动等待（`src/waiting.py`）与「不再傻等」的改造效果。

无需 pytest，直接 `python tests/test_waiting.py`。

分两部分：
  A. `wait_until` / `wait_gone` / `wait_visible` / `wait_hidden` 的语义正确性。
  B. 静态审计：确认关键路径上的固定 sleep 已被条件等待取代
     （这是本轮效率优化的核心，防止日后改回去）。
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

# ★ 输出被重定向到文件/管道时，Windows 会用 GBK，日志里的 ⚠ 会让
#   print 直接抛 UnicodeEncodeError（实测退出码 1）。先加固编码。
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


# ==================================================== A. 等待语义
print("=== A. waiting.py 语义 ===")
from xyxbot.waiting import (WaitResult, poll_interval, wait_gone, wait_hidden,
                         wait_until, wait_visible)

# A1 条件早就成立 → 必须立刻返回（不能有固定最小等待）
t0 = time.time()
r = wait_until(lambda: True, timeout=5.0)
el = time.time() - t0
check("已成立 → 立即返回且仅 1 次轮询", (r.ok, r.polls), (True, 1))
check_true("已成立 → 耗时 <100ms", el < 0.1, f"elapsed={el:.3f}s")

# A2 条件在第 N 次成立 → 在第 N 次返回（不是等满 timeout）
n = {"i": 0}


def _late():
    n["i"] += 1
    return n["i"] >= 3


t0 = time.time()
r2 = wait_until(_late, timeout=3.0)
el2 = time.time() - t0
check("第 3 次成立 → polls=3", r2.polls, 3)
check_true("远早于 timeout 返回", el2 < 0.5, f"elapsed={el2:.3f}s")

# A3 timeout 被尊重，且不会 oversleep 超过 deadline
t0 = time.time()
r3 = wait_until(lambda: False, timeout=0.4)
el3 = time.time() - t0
check("超时 → ok=False", r3.ok, False)
check_true("超时耗时贴近 timeout（不 oversleep）",
           0.35 < el3 < 0.9, f"elapsed={el3:.3f}s")

# A4 谓词抛异常按「未满足」处理，绝不外抛
m = {"i": 0}


def _boom_then_ok():
    m["i"] += 1
    if m["i"] < 3:
        raise RuntimeError("DOM 还没好")
    return "done"


r4 = wait_until(_boom_then_ok, timeout=2.0)
check("谓词异常被吞掉并最终成功", (r4.ok, r4.value), (True, "done"))

# A5 wait_gone：一开始就没了 → 立即成功
t0 = time.time()
r5 = wait_gone(lambda: 0, timeout=5.0)
check_true("wait_gone 一开始就消失 → 立即成功",
           r5.ok and time.time() - t0 < 0.1)

# A6 wait_gone：第 3 次才消失
k = {"i": 0}


def _gone_late():
    k["i"] += 1
    return 1 if k["i"] < 3 else 0


r6 = wait_gone(_gone_late, timeout=2.0)
check("wait_gone 第 3 次消失 → polls=3", (r6.ok, r6.polls), (True, 3))

# A7 退避：起始快、增长、封顶
check("退避起始 = 0.04", poll_interval(0.1), 0.04)
check_true("退避随时间增长", poll_interval(3.0) > 0.04)
check("退避封顶 = 0.25", poll_interval(1000.0), 0.25)

# A8 on_poll 心跳
beats = []
wait_until(lambda: False, timeout=0.3, on_poll=lambda i: beats.append(i))
check_true("on_poll 心跳被调用", len(beats) > 0, f"beats={len(beats)}")

# A9 wait_visible / wait_hidden（用假 page，模拟异步渲染）
class _Loc:
    def __init__(self, vis):
        self._v = vis

    @property
    def first(self):
        return self

    def is_visible(self, timeout=None):
        return self._v


class _Page:
    def __init__(self):
        self.t0 = time.time()

    def locator(self, sel):
        if sel == ".late":
            return _Loc(time.time() - self.t0 > 0.25)
        if sel == ".now":
            return _Loc(True)
        return _Loc(False)      # .never


pg = _Page()
t0 = time.time()
ok = wait_visible(pg, [".never", ".late"], timeout=3.0)
el = time.time() - t0
check_true("wait_visible 多候选命中（非固定等待）",
           ok and 0.2 < el < 1.0, f"ok={ok} elapsed={el:.2f}s")

t0 = time.time()
ok2 = wait_visible(pg, [".now"], timeout=3.0)
check_true("wait_visible 已可见 → 立即", ok2 and time.time() - t0 < 0.15)

check("wait_visible 永不可见 → False",
      wait_visible(pg, [".never"], timeout=0.3), False)

t0 = time.time()
ok3 = wait_hidden(pg, [".never"], timeout=2.0)
check_true("wait_hidden 已隐藏 → 立即", ok3 and time.time() - t0 < 0.15)

check("wait_hidden 一直可见 → False",
      wait_hidden(pg, [".now"], timeout=0.3), False)

# A10 WaitResult 可直接当 bool
check("WaitResult 支持真值判断", bool(WaitResult(ok=True)), True)
check("WaitResult 失败为假", bool(WaitResult(ok=False)), False)

# ==================================================== B. 静态审计
print("\n=== B. 关键路径已不再「傻等」（静态审计） ===")
ai_src = S.module_source("src/ai.py")
tree = ast.parse(ai_src)


def literal_sleeps(func_name: str) -> float:
    """某函数体内的**字面量** sleep 合计秒数。"""
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == func_name:
            tot = 0.0
            for c in ast.walk(node):
                if (isinstance(c, ast.Call)
                        and isinstance(c.func, ast.Attribute)
                        and c.func.attr == "sleep" and c.args):
                    a = c.args[0]
                    if isinstance(a, ast.Constant) and isinstance(
                            a.value, (int, float)):
                        tot += a.value
            return tot
    return -1.0


# 本轮重点改造的函数：固定 sleep 必须大幅下降
EXPECT = {
    "relate_chapters": 1.0,          # 原 6.2s
    "wait_generation": 0.1,          # 原 2.7s（含开头 1.5 + 完成 1.2）
    "close_continue_dialog": 1.0,    # 原 3.2s
    "wait_body_change": 0.1,         # 原 0.9s
    "select_all_body": 0.5,          # 原 1.9s
    "replace_review_result": 0.5,    # 原 1.2s
    "wait_shortcut_loaded": 0.1,     # 原 1.0s（固定"再等 1 秒"）
    "select_model": 1.0,             # 原 3.6s
    "set_associate_level": 1.0,      # 原 1.5s
    "pick_shortcut": 1.0,            # 原 3.0s
    "fill_review_text": 0.1,         # 原 1.6s
    "pick_review_requirement": 1.0,  # 原 2.3s
    "dismiss_dialogs": 1.0,          # 原 2.2s
}
for fn, limit in EXPECT.items():
    got = literal_sleeps(fn)
    check_true(f"{fn} 固定 sleep {got:.1f}s ≤ {limit}s", 0 <= got <= limit,
               f"got={got}")

# 轮询间隔必须已经收紧
import inspect
from xyxbot import ai as AI

_wg_poll = AI.wait_generation.__defaults__[1]
_wr_poll = AI.wait_review_done.__defaults__[1]
_ws_poll = AI.wait_shortcut_loaded.__defaults__[1]
check_true(f"wait_generation poll 默认 {_wg_poll} ≤0.5s", _wg_poll <= 0.5)
check_true(f"wait_review_done poll 默认 {_wr_poll} ≤0.5s", _wr_poll <= 0.5)
check_true(f"wait_shortcut_loaded poll 默认 {_ws_poll} ≤0.2s", _ws_poll <= 0.2)

# 关键函数必须真的用条件等待
for fn, needle in [
    ("relate_chapters", "wait_until"),
    ("wait_generation", "wait_until"),
    ("close_continue_dialog", "wait_gone"),
    ("wait_body_change", "wait_until"),
    ("select_all_body", "wait_until"),
    ("replace_review_result", "wait_until"),
    ("fill_review_text", "wait_until"),
    ("pick_review_requirement", "wait_until"),
    ("dismiss_dialogs", "wait_gone"),
]:
    src = inspect.getsource(getattr(AI, fn))
    check_true(f"{fn} 使用条件等待", needle in src)

# 总固定 sleep 预算必须明显下降（改造前 36.0s）
tot = 0.0
for node in ast.walk(tree):
    if isinstance(node, ast.FunctionDef):
        tot += max(0.0, literal_sleeps(node.name))
check_true(f"ai.py 固定 sleep 总量 {tot:.1f}s < 12s（改造前 36.0s）", tot < 12.0)


# ==================================================== C. 真机调试抓到的 bug 的回归
# 以下每一条都对应 2026-10-04 用真机诊断（diag_latency / diag_probe / diag_click）
# 实测抓到的**具体缺陷**，都附上了当时的实测数字。
print("\n=== C. 真机调试所发现缺陷的回归检查 ===")

_SRC = S.PKG
_AI_SRC = S.module_source("src/ai.py")
_ai_tree = ast.parse(_AI_SRC)


def _func_src(name: str) -> str:
    return inspect.getsource(getattr(AI, name))


# --- C1 「15 秒黑洞」：任何裸 inner_text() 都会等到默认超时 -------------------
# 实测：locator('.__nope__').first.inner_text() → 15009ms
#       current_associate_level 3 次 = 45.03s（15.01s/次）
_bare = []
for _p in S.pkg_py_files():          # 含子包（ai/ 拆分后仍被审到）
    try:
        _t = ast.parse(_p.read_text(encoding="utf-8"))
    except Exception:
        continue
    for _n in ast.walk(_t):
        if (isinstance(_n, ast.Call)
                and isinstance(_n.func, ast.Attribute)
                and _n.func.attr == "inner_text"
                and not any(k.arg == "timeout" for k in _n.keywords)):
            _bare.append(f"{_p.name}:{_n.lineno}")
check_true(f"src/ 下没有裸 inner_text()（发现 {len(_bare)} 处 {_bare[:4]}）",
           not _bare)

check_true("current_associate_level 走 _text_of（带超时+count 前置检查）",
           "_text_of" in _func_src("current_associate_level"))
for _fn in ("current_model", "current_shortcut", "current_review_requirement"):
    check_true(f"{_fn} 走 _text_of", "_text_of" in _func_src(_fn))

# --- C2 点击超时：残留遮罩会让长超时点击必然白等满 -------------------------
# 实测：loc.click(timeout=4000) → 4096ms 超时；JS 点击 6ms 成功
check_true("存在 _safe_click（短超时→JS→force 三档降级）",
           hasattr(AI, "_safe_click"))
check_true(f"CLICK_FAST_TIMEOUT={getattr(AI, 'CLICK_FAST_TIMEOUT', 9999)} ≤ 1000ms",
           getattr(AI, "CLICK_FAST_TIMEOUT", 9999) <= 1000)
check_true("_click_first 用 CLICK_FAST_TIMEOUT", 
           "CLICK_FAST_TIMEOUT" in _func_src("_click_first"))

# 热点路径上不允许再出现 ≥3000ms 的字面量点击超时
_HOT = ["select_all_body", "pick_review_requirement", "open_chapter",
        "open_review_pane", "close_review_pane", "replace_review_result",
        "close_continue_dialog", "start_review", "select_model",
        "open_shortcut_panel", "fill_review_text"]
_bad = [f for f in _HOT
        if any(f"timeout={t}" in _func_src(f) for t in (3000, 4000, 5000))]
check_true(f"热点函数里没有 ≥3000ms 的点击超时（发现 {_bad}）", not _bad)

# 全文件层面：≥3000ms 的 .click 超时应该所剩无几（只留兜底/罕见路径）
_slow_sites = []
for _n in ast.walk(_ai_tree):
    if (isinstance(_n, ast.Call) and isinstance(_n.func, ast.Attribute)
            and _n.func.attr == "click"):
        for _k in _n.keywords:
            if _k.arg == "timeout" and isinstance(_k.value, ast.Constant) \
                    and isinstance(_k.value.value, int) and _k.value.value >= 3000:
                _slow_sites.append(_n.lineno)
check_true(f"ai.py 里 ≥3000ms 的 .click 超时 ≤4 处（现 {len(_slow_sites)} 处"
           f" {_slow_sites}）", len(_slow_sites) <= 4)

# --- C3 relate_chapters：曾经的"第2章起静默失效" ---------------------------
# 旧代码用 `.n-modal button` 过滤 has_text="最近5章" 当锚点，而那个文字
# 只在当前档位正好是 5 章时才存在 → 第 2 章起找不到 → 白等 6 秒 → 返回 False
# 且调用方忽略返回值 → 静默丢失"关联章节"（内容质量事故）
_rel = _func_src("relate_chapters")
check_true('relate_chapters 不再用硬编码锚点 has_text="最近5章"',
           'has_text="最近5章"' not in _rel,
           "旧锚点回来了会导致第2章起失效（按钮文字变成「最近10章」）")
check_true("relate_chapters 用 current_relate_count 做幂等判断",
           "current_relate_count" in _rel)
check_true("存在 current_relate_count（回读当前档位）",
           hasattr(AI, "current_relate_count"))
check_true("存在 _relate_dropdown（按 overflow-hidden 类定位下拉）",
           hasattr(AI, "_relate_dropdown"))
# ★ 2026-10-06：定位逻辑拆成了 _relate_dropdown_in（可在指定容器里找），
#   _relate_dropdown 只负责"选哪个容器"。所以两处任一含 overflow-hidden 即可。
check_true("定位下拉用 overflow-hidden 区分「最近3章」",
           "overflow-hidden" in _func_src("_relate_dropdown")
           or "overflow-hidden" in _func_src("_relate_dropdown_in"))
# 旧代码结尾的 wait_gone(text=最近N章) 必然超时 3 秒（选完后按钮文字就是它）
check_true("relate_chapters 不再调 wait_gone（那条判据必然超时 3 秒）",
           "wait_gone" not in _rel)
# 调用方必须检查返回值并告警
_cont = _func_src("ai_continue")
check_true("ai_continue 检查 relate_chapters 返回值并告警",
           "if not relate_chapters" in _cont)

# --- C4 wait_shortcut_loaded 的 20 秒死等 -----------------------------------
# 实测：面板没打开时它一直数到 timeout=20s；pick_review_requirement 因此
#       3 次调用白等 57.9 秒（579 次 0.1s 轮询）
_wsl = _func_src("wait_shortcut_loaded")
check_true("wait_shortcut_loaded 先判断面板是否存在（否则省 20 秒空转）",
           "shortcut-picker-modal" in _wsl.split("t0 = time.time()")[0])

# --- C5 每章固定 sleep：已全部条件化 ----------------------------------------
for _fn in ("start_generate", "accept_result", "start_review",
            "open_review_pane", "close_review_pane", "open_chapter"):
    _s = _func_src(_fn)
    check_true(f"{_fn} 不再固定 sleep（改用条件等待）",
               "time.sleep" not in _s or "wait_" in _s,
               "见 EFFICIENCY_REPORT 的「单章固定等待」表")

# ai_auto_chapter 的 settle 不再是无条件 sleep
_auto = _func_src("ai_auto_chapter")
check_true("ai_auto_chapter 的 settle 改成有上限的非阻塞等待",
           "time.sleep(settle)" not in _auto)

# --- C6 控制台编码：日志一落盘就崩的坑 --------------------------------------
check_true("存在 src/console.py:enable_utf8",
           (_SRC / "console.py").exists()
           and "def enable_utf8" in (_SRC / "console.py")
           .read_text(encoding="utf-8"))
for _entry in (S.pkg_file("cli.py"), ROOT / "run_gui.py"):
    _t = _entry.read_text(encoding="utf-8")
    check_true(f"{_entry.relative_to(ROOT).as_posix()} 调用了 enable_utf8"
               f"（重定向到文件时不会崩）",
               "enable_utf8" in _t)
for _tf in ("test_fixes.py", "test_gui_pages.py", "test_waiting.py"):
    _t = (ROOT / "tests" / _tf).read_text(encoding="utf-8")
    check_true(f"{_tf} 在 os._exit 前 flush 输出",
               "sys.stdout.flush()" in _t)

# --- C7 ★★ 最严重的一个：谓词签名写错 → 等待必然超时且完全静默 --------------
# 实测代价：`wait_until(gen_finished, timeout=300)` 让**每章干等满 300 秒**
#           才判"生成失败"，而生成其实 ~9 秒就完成了。
#           `wait_until(review_pane_open, ...)` 同理，每章白等 8.5 秒。
S.add_tools_to_path()   # 审计工具已从仓库根搬到 tools/audit/，由 _support 定位
import audit_wait_args  # noqa: E402  （tools/audit/audit_wait_args.py）

_n_files, _probs = audit_wait_args.audit_all(ROOT)
check_true(f"全项目 {_n_files} 个文件的 wait_until/wait_gone 谓词签名都正确"
           f"（问题 {_probs[:3]}）", not _probs)

# 这两个具体调用点必须包了 lambda 或等价的无参闭包（防回归）
#   ★ 2026-10-04 更新：wait_generation 的判据从 `lambda: gen_finished(page)`
#     升级为 `_finished_and_trustworthy`（内部仍调用 gen_finished，但额外
#     要求"本轮确实启动过"，防止**残留结果页**被立刻当成已完成、读到旧字数）。
#     两者都是**零参数**可调用对象，签名正确性一致。
_wg_src = _func_src("wait_generation")
check_true("wait_generation 的谓词是零参可调用（lambda 或本地闭包）",
           ("lambda: gen_finished(page)" in _wg_src
            or ("def _finished_and_trustworthy()" in _wg_src
                and "wait_until(_finished_and_trustworthy" in _wg_src)),
           "必须传零参谓词，否则 wait_until 每轮抛 TypeError → 必然超时")
check_true("wait_generation 内部仍以 gen_finished 为完成判据",
           "gen_finished(page)" in _wg_src)
check_true("open_review_pane 用 lambda 包 review_pane_open",
           "lambda: review_pane_open(page)" in _func_src("open_review_pane"))

# --- C8 waiting.py 必须把谓词异常喊出来（不再静默吞掉）----------------------
_wait_src = (_SRC / "waiting.py").read_text(encoding="utf-8")
check_true("waiting.py 有 _predicate_error_note（谓词报错时告警）",
           "_predicate_error_note" in _wait_src)
check_true("wait_until 超时 detail 里带上最后一次谓词异常",
           "谓词一直在报错" in _wait_src)
check_true("waiting.py 对 TypeError 专门提示'签名写错'",
           "签名写错" in _wait_src)

# 语义验证：传一个需要参数的函数进去 → 必须报错（而不是无声超时）
import io as _io
import contextlib as _ctx
_buf = _io.StringIO()
with _ctx.redirect_stdout(_buf):
    _bad = wait_until(lambda page=None: False, timeout=0.2, interval=0.05,
                      desc="正常路径不该有警告")
check_true("正常谓词不会触发告警", "[waiting]" not in _buf.getvalue())

_buf2 = _io.StringIO()
with _ctx.redirect_stdout(_buf2):
    def _needs_page(page):                       # 故意要求参数
        return True
    r_bad = wait_until(_needs_page, timeout=0.25, interval=0.05,
                       desc="签名写错的谓词")
check_true("签名写错的谓词 → 超时且 ok=False", r_bad.ok is False)
check_true("签名写错的谓词 → 打印了 [waiting] 告警",
           "[waiting]" in _buf2.getvalue(),
           f"实际输出：{_buf2.getvalue()[:120]!r}")
check_true("签名写错的谓词 → 提示『签名写错』",
           "签名写错" in _buf2.getvalue())
check_true("超时 detail 里带上了 TypeError",
           "TypeError" in (r_bad.detail or ""))

# ==================================================== D. 行为级回归（假 page）
# ★★ 这一节是全场最重要的测试：C7 的静态审计只能查"裸名字"谓词，
#    但真正的教训是——**等待逻辑写错时会静默超时**，静态检查不完备。
#    所以这里用一个"假 page"把真实的等待函数跑起来，直接断言
#    「条件满足时立刻返回、而不是等满超时」。
#    实测代价参考：`wait_until(gen_finished)` 让每章干等满 300 秒。
print("\n=== D. 等待函数的真实行为（假 page，不联网）===")


class _FakeLoc:
    """只实现等待/点击路径真正会用到的那几个方法。"""

    def __init__(self, page, sel):
        self._p = page
        self._s = sel

    @property
    def first(self):
        return self

    def count(self):
        return self._p.count_of(self._s)

    def is_visible(self, timeout=None):
        return self._p.count_of(self._s) > 0

    def locator(self, sel):
        return _FakeLoc(self._p, sel)

    def filter(self, **_kw):
        return self

    def nth(self, _i):
        return self

    def inner_text(self, timeout=None):
        return self._p.text_of(self._s)

    def get_attribute(self, _n):
        return ""

    def input_value(self, timeout=None):
        return ""

    def bounding_box(self):
        return {"x": 0, "y": 0, "width": 10, "height": 10}

    def click(self, timeout=None, force=False, position=None):
        self._p.clicks.append(self._s)

    def evaluate(self, _js):
        self._p.clicks.append("JS:" + self._s)

    def scroll_into_view_if_needed(self, timeout=None):
        return None

    def fill(self, *_a, **_k):
        return None

    def type(self, *_a, **_k):
        return None

    def screenshot(self, **_k):
        return None


class _FakePage:
    """极简假页面：用 `计数规则` 决定每个选择器"存在几个"。"""

    def __init__(self, rules):
        self.rules = rules
        self.clicks: list[str] = []
        self.now = lambda: 0.0

    def count_of(self, sel):
        for key, fn in self.rules:
            if key in sel:
                return fn()
        return 0

    def text_of(self, sel):
        if "word-count" in sel:
            return "220"          # 让「等字数渲染」那步也能立刻满足
        return ""

    def locator(self, sel):
        return _FakeLoc(self, sel)

    def evaluate(self, js):
        return None

    def screenshot(self, **_k):
        return None

    def keyboard(self):
        raise AssertionError("假 page 不该用到 keyboard")


# ---- D1 wait_generation：生成一完成就必须返回（不是等满 timeout）----------
_t_start = time.time()
_fp = _FakePage([
    (".n-modal", lambda: 1),
    ("重新生成", lambda: 1 if time.time() - _t_start > 0.25 else 0),
    ("采纳使用", lambda: 1 if time.time() - _t_start > 0.25 else 0),
    ("停止生成", lambda: 0),
    ("n-button--loading", lambda: 0),
    ("word-count", lambda: 1),
])
_t0 = time.time()
_ok_gen = AI.wait_generation(_fp, timeout=6.0, poll=0.05)
_el_gen = time.time() - _t0
check_true("wait_generation 条件满足后返回 True（不再必然超时）", _ok_gen)
check_true(f"wait_generation 立即返回（{_el_gen:.2f}s « 6s 超时）",
           _el_gen < 1.0,
           "若这里接近 6s，说明谓词又被静默吞掉了")

# 反例：条件永不满足 → 必须超时且返回 False（超时语义仍要正确）
_fp2 = _FakePage([(".n-modal", lambda: 1)])
_t0 = time.time()
_ok2 = AI.wait_generation(_fp2, timeout=0.6, poll=0.05)
check_true("wait_generation 条件不满足 → 超时返回 False",
           _ok2 is False and (time.time() - _t0) >= 0.5)

# ---- D2 open_review_pane：点完必须立刻认账（不是白等 8.5 秒）-------------
_clicked = {"v": False}
_fp3 = _FakePage([
    ("AI审稿", lambda: 1),
    ("待审文本", lambda: 1 if _clicked["v"] else 0),
    (".n-modal", lambda: 0),
    ("n-notification", lambda: 0),
])
_orig_click = _FakeLoc.click


def _click_mark(self, timeout=None, force=False, position=None):
    _orig_click(self, timeout=timeout, force=force, position=position)
    if "AI审稿" in self._s:
        _clicked["v"] = True


_FakeLoc.click = _click_mark
try:
    _t0 = time.time()
    _ok_pane = AI.open_review_pane(_fp3)
    _el_pane = time.time() - _t0
finally:
    _FakeLoc.click = _orig_click
check_true("open_review_pane 点完立即返回 True（不再必然超时）", _ok_pane)
check_true(f"open_review_pane 立即返回（{_el_pane:.2f}s « 3.6s 超时）",
           _el_pane < 1.5,
           "若接近 3.6s，说明 review_pane_open 又被当无参谓词传进去了")

# ---- D3 三个"回读"函数在元素不存在时必须立刻返回空串 ----------------------
# 实测：裸 inner_text() 会等到默认 15 秒（current_associate_level 45.03s/3 次）
_fp4 = _FakePage([])          # 任何选择器都不存在
for _fn, _call in (
    ("current_associate_level", lambda: AI.current_associate_level(_fp4)),
    ("current_model", lambda: AI.current_model(_fp4)),
    ("current_shortcut", lambda: AI.current_shortcut(_fp4)),
    ("current_review_requirement",
     lambda: AI.current_review_requirement(_fp4)),
    ("current_relate_count", lambda: AI.current_relate_count(_fp4)),
):
    _t0 = time.time()
    _v = _call()
    _el = time.time() - _t0
    check_true(f"{_fn} 元素不存在时立刻返回（{_el*1000:.0f}ms < 200ms）",
               _el < 0.2, f"got={_v!r} elapsed={_el:.3f}s")

check("current_relate_count 读不到按钮 → -1", AI.current_relate_count(_fp4), -1)

# ==================================================== 汇总
print("\n" + "=" * 60)
print(f"  通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
if FAIL:
    print("  失败列表：")
    for f in FAIL:
        print(f"    - {f}")
print("=" * 60)

# ★ flush 必须加：os._exit 不会刷缓冲区，
#   一旦把输出重定向到文件/管道，测试结果就整个丢了（实测踩过）。
sys.stdout.flush()
sys.stderr.flush()
os._exit(1 if FAIL else 0)

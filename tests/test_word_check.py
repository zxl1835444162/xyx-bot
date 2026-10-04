# -*- coding: utf-8 -*-
"""回归测试：续写字数「达标/重生成」决策 + UI 接线（2026-10-04 用户报障）。

用户原话：
    「这个续写字数不对，重新生成，这个逻辑，你是没有加上？还是说你漏掉了？
     我 2700 的字数，竟然过了 2100-2300 的限制」

两个真问题：
    A. src/ai.py 的兜底分支虽然是"取最后一轮"，但 **UI 把 max_retry 写死成 0**，
       等于"一轮定生死" ⇒ 任何字数都被直接采纳，区间形同虚设
    B. UI 还把区间硬编码成 100~5000，进一步让限制失效

本文件用**纯逻辑**验证（不需要浏览器/窗口）：
    1. 决策规则：太多、太少都要重生成；重试用完取**最后一次**的结果
    2. UI 不再写死 max_retry / 区间（静态断言，防退化）
    3. 防残留值：open_continue_dialog / wait_generation 的加固存在
"""
from __future__ import annotations

import ast
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

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


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def _strip_strings(src: str) -> str:
    """剥掉所有字符串常量（含注释在 AST 里本就不出现），用于静态断言。"""
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return src
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            node.value = "\x00"
    return ast.unparse(tree)


# ============================================ 1. 决策规则（复刻主循环）
print("=== 1. 字数决策规则 ===")

MIN_W, MAX_W = 2100, 2300


def decide(tries, max_retry, best_effort=True, hard_min=0):
    """复刻 src/ai.py::generate_with_word_check 的主循环决策。

    返回 (最终动作, 采纳字数, 各轮)。
    动作 ∈ {"达标采纳", "兜底采纳", "失败"}
    """
    for attempt, cnt in enumerate(tries):
        if MIN_W <= cnt <= MAX_W:
            return ("达标采纳", cnt, list(tries[:attempt + 1]))
        if attempt >= max_retry:
            if hard_min > 0 and cnt >= hard_min and cnt < MIN_W:
                return ("兜底采纳", cnt, list(tries[:attempt + 1]))
            if best_effort and cnt > 0:
                return ("兜底采纳", cnt, list(tries[:attempt + 1]))
            return ("失败", -1, list(tries[:attempt + 1]))
    return ("失败", -1, list(tries))


# ★ 核心回归：太多也要重生成（不是直接采纳）
act, w, _ = decide([2700, 2650, 2500, 2400], max_retry=3)
check("超过上限会重生成（不是首轮直接采纳）", act, "兜底采纳")
check("重试用完后取【最后一次】的结果", w, 2400)
check("2700 不会被当成首轮达标", decide([2700], max_retry=0)[0], "兜底采纳")
check("单轮兜底取的就是那一轮", decide([2700], max_retry=0)[1], 2700)

# ★ 太少也要重生成
act, w, _ = decide([1800, 1900, 2000, 2050], max_retry=3)
check("低于下限会重生成", act, "兜底采纳")
check("重试用完后取【最后一次】（偏低）", w, 2050)

# ★ 中途达标 → 立即采纳，不浪费重试
act, w, rounds = decide([2700, 2200, 2600, 2900], max_retry=3)
check("中途达标立即采纳", act, "达标采纳")
check("达标值取自那一轮", w, 2200)
check("达标后不再多生成", len(rounds), 2)

# ★ 一轮就达标
check("一轮达标", decide([2250], max_retry=3)[:2], ("达标采纳", 2250))

# ★ 边界：正好落在上下限
check("恰好等于下限 → 达标", decide([MIN_W], max_retry=3)[0], "达标采纳")
check("恰好等于上限 → 达标", decide([MAX_W], max_retry=3)[0], "达标采纳")
check("下限-1 → 不达标", decide([MIN_W - 1], max_retry=0)[1], MIN_W - 1)
check("上限+1 → 不达标", decide([MAX_W + 1], max_retry=0)[1], MAX_W + 1)

# ★ best_effort=False → 严格失败，不点采纳
check("best_effort=False 时重试用完判失败",
      decide([2700], max_retry=0, best_effort=False)[0], "失败")

# ★ 重试次数真的生效（max_retry 越大，尝试越多）
_, _, t3 = decide([3000, 3000, 2400], max_retry=3)
check("max_retry=3 会走到第 3 轮", len(t3), 3)
_, _, t1 = decide([3000, 2500], max_retry=1)
check("max_retry=1 只走 2 轮（首轮+1 次重试）", len(t1), 2)

# ★ 读不到字数（-1）不能当成达标
check("字数 -1 不采纳", decide([-1], max_retry=0)[0], "失败")

def _real_code(rel: str) -> str:
    """只保留**真实代码**：注释本就不进 AST，字符串常量也剥掉。

    ★ 为什么必须这样：直接对源码文本做子串匹配，会把**注释里提到**的
      `max_retry=0`（我在修复说明里引用了旧写法）误判成"还在写死"。
    """
    return _strip_strings(_read(rel))


# ============================================ 2. UI 不再写死（静态契约）
print("\n=== 2. UI 接线（防退化）===")

flow_code = _real_code("ui/pages/ai_flow.py")

# ★ 核心：不许再出现硬编码的 max_retry=0
check_true("ai_flow.py 真实代码里没有 max_retry=0",
           "max_retry=0" not in flow_code.replace(" ", ""),
           "找到 max_retry=0，说明又写死了")
check_true("ai_flow.py 使用界面上的 max_retry",
           "max_retry=max_retry" in flow_code,
           "应把界面的「最多重生成」传下去")

# ★ 区间不许再写死成 100/5000
check_true("ai_flow.py 不再把下限写死为 100",
           "or 100" not in flow_code,
           "`_int_or(..., 100) or 100` 会让区间失效")
check_true("ai_flow.py 不再把上限写死为 5000",
           "or 5000" not in flow_code,
           "`_int_or(..., 5000) or 5000` 会让区间失效")
check_true("ai_flow.py 使用 DEFAULT_MIN_WORDS",
           "DEFAULT_MIN_WORDS" in flow_code)
check_true("ai_flow.py 使用 DEFAULT_MAX_WORDS",
           "DEFAULT_MAX_WORDS" in flow_code)
check_true("ai_flow.py 使用 DEFAULT_MAX_RETRY",
           "DEFAULT_MAX_RETRY" in flow_code)

# ============================================ 3. 防「残留结果页」加固
print("\n=== 3. 防残留结果页读到旧字数 ===")

ai_src = _read("src/ai.py")
ai_code = _real_code("src/ai.py")

check_true("存在 _stale_result_present",
           "def _stale_result_present" in ai_src)
check_true("存在 _close_stale_result",
           "def _close_stale_result" in ai_src)
check_true("open_continue_dialog 会先关残留结果页",
           "_close_stale_result(page)" in ai_src)
check_true("wait_generation 有 started_ok 机制",
           "started_ok" in ai_src)
check_true("wait_generation 有 _finished_and_trustworthy",
           "_finished_and_trustworthy" in ai_src)
check_true("不再用裸 lambda gen_finished 当唯一判据",
           "wait_until(lambda: gen_finished(page)" not in ai_src,
           "裸判据会让残留结果页被立刻当成已完成")

# 已删除的复杂逻辑不应复活
check_true("_pick_closest 已移除（用户要求简单兜底）",
           "def _pick_closest" not in ai_src)

# ★ 兜底语义必须在真实代码里（防有人把「超过也认」改回"直接采纳"）
check_true("兜底分支用 best_effort 包着（不会无条件采纳）",
           "best_effort and cnt > 0" in ai_code)
check_true("达标判定用的是闭区间 [min, max]",
           "min_words <= cnt <= max_words" in ai_code)
check_true("超上限/不足走同一条重生成路径（why 只用于日志）",
           "cnt < min_words" in ai_code)

# ============================================ 4. 参数一路传到最底层
print("\n=== 4. 参数透传 ===")

check_true("ai_batch_chapters 收 max_retry",
           "max_retry" in ai_src)
check_true("download 路径 ai_auto_chapter 有 max_retry 形参",
           "max_retry: int = 5" in ai_src)

# main.py 的 CLI 也应当传（别再写死）
main_code = _real_code("main.py")
check_true("main.py 真实代码里没有 max_retry=0",
           "max_retry=0" not in main_code.replace(" ", ""),
           "CLI 那条路径也在写死")
check_true("main.py CLI 把解析出的 max_retry 传下去",
           "max_retry=max_retry" in main_code)

# ============================================ 5. 审稿填写加固
print("\n=== 5. 审稿「追加指令」填写加固 ===")

# ★ 用户问：「审稿追加指令的填写逻辑，不和续写填写的逻辑一致吗？
#            怎么会有时候出现差错？」
#   答：不一致。续写填的是**自造纯文本**，不依赖页面；
#   审稿要**先读页面正文再拼接**，多一步"读"就多一个时序风险。
#   本节的断言确保这些风险点已被堵住。

check_true("存在 read_review_box（读站点自带正文）",
           "def read_review_box" in ai_src)
check_true("存在 read_body_settled（等正文就绪再读）",
           "def read_body_settled" in ai_src)
check_true("read_body_settled 优先读待审文本框",
           "box = read_review_box(page)" in ai_src,
           "应优先用站点填好的待审文本，避免读到上一章正文")
check_true("读不到时才退回编辑器正文",
           "退回用编辑器正文" in ai_src)
check_true("拼接正文时用 read_body_settled 而非瞬时 get_body_text",
           "body = read_body_settled(page)" in ai_src)
check_true("不再在拼接处瞬时读正文",
           "body = get_body_text(page) if read_body" not in ai_src,
           "瞬时读会在编辑器重渲染时读到空/半截/上一章正文")
check_true("open_chapter 之后会等正文就绪",
           "read_body_settled(page, timeout=8.0)" in ai_src)
check_true("ai_review 检查 fill_review_text 的返回值",
           "if not fill_review_text(page" in ai_src,
           "丢弃返回值会让「填失败」静默通过")
check_true("待审文本填失败会终止审稿",
           "ai_review_fill_failed" in ai_src)

# _settle 判据强化（长度 + 前缀，而不是只比尾部 40 字）
check_true("_settle 接受 head/want_len 参数",
           "def _settle(expected: str, head: str, want_len: int)" in ai_src)
check_true("_settle 会校验长度容差",
           "tol = max(5, int(want_len * 0.02))" in ai_src)
check_true("_settle 会校验前缀",
           "if head and head not in cur" in ai_src)

# ============================================ 汇总
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

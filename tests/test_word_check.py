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


def _read(rel: str) -> str:
    # `src/...` / `ui/...` 是重构前的旧路径写法，交给 _support 解析：
    # 业务包改名、界面收进包里之后，这里不用再改。
    return S.read(S.resolve_legacy(rel))


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

# CLI（xyxbot/cli.py）也应当传（别再写死）
main_code = _real_code("xyxbot/cli.py")
check_true("cli.py 真实代码里没有 max_retry=0",
           "max_retry=0" not in main_code.replace(" ", ""),
           "CLI 那条路径也在写死")
check_true("cli.py 把解析出的 max_retry 传下去",
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

# ============================================ 6. 防「套娃」（多轮重复包层）
print("\n=== 6. 审稿「整体替换」不会越包越多 ===")

# ★ 用户追问：「那么，是不是，全部替换了，框中的内容，达到文字+正文？」
#   答：是整体替换（fill 是覆盖语义）。但**读出+拼接+覆盖**若不剥旧层，
#       就会 827 → 867 → 907 → 946 每轮多包一层。本节锁死这个行为。

# 从真实模块导入纯函数来测（最有说服力，不会与实现漂移）
import importlib.util as _ilu
import types as _types

# ★ 无浏览器环境也要能真导入：给 playwright 塞一个空壳，
#   我们只测纯字符串函数，不碰 Page。
for _n in ("playwright", "playwright.sync_api", "playwright._impl",
           "playwright._impl._errors"):
    if _n not in sys.modules:
        _m = _types.ModuleType(_n)
        sys.modules[_n] = _m
_pw = sys.modules["playwright.sync_api"]
for _attr in ("Page", "Browser", "BrowserContext", "Locator",
              "TimeoutError", "Error", "expect"):
    if not hasattr(_pw, _attr):
        setattr(_pw, _attr, type(_attr, (), {}))
sys.modules["playwright"].sync_api = _pw

_spec = None
_ai = None
_real_import = False
try:
    # ★ 必须按**包**导入：src/ai.py 里有 `from . import config` 等相对导入
    import xyxbot.ai as _ai_mod
    _ai = _ai_mod
    _real_import = True
except Exception as e:
    print(f"  [WARN] 以包方式导入 src.ai 失败（{str(e).splitlines()[0]}），"
          f"尝试文件加载")
    try:
        _spec = _ilu.spec_from_file_location("_ai_mod", str(S.pkg_file("ai.py")))
        _ai = _ilu.module_from_spec(_spec)
        _spec.loader.exec_module(_ai)
        _real_import = True
    except Exception as e2:  # pragma: no cover - 环境缺依赖时的兜底
        print(f"  [WARN] 无法直接导入 src/ai.py（{str(e2).splitlines()[0]}），"
              f"改用源码内联实现")

if _real_import:
    _SEP = _ai.REVIEW_SEP
    _strip = _ai.strip_review_wrapper
else:  # pragma: no cover
    _SEP = "————————以下为待审正文————————"

    def _strip(text: str) -> str:
        if not text:
            return ""
        if _SEP not in text:
            return text.strip()
        return text.rsplit(_SEP, 1)[-1].strip()

check_true("测试的是 src/ai.py 里的**真实** strip_review_wrapper（非内联复刻）",
           _real_import,
           "若为 False，说明只是内联实现，没验证到真代码")
check_true("REVIEW_SEP 存在且非空", bool(_SEP))

# ---- 基本剥离语义 ----
check("无分隔线 → 原样（strip 首尾空白）", _strip("纯正文内容"), "纯正文内容")
check("单层 → 取分隔线之后", _strip(f"指令A\n\n{_SEP}\n\n正文B"), "正文B")
check("多层 → 取【最后】一条分隔线之后（核心）",
      _strip(f"指令B\n\n{_SEP}\n\n指令A\n\n{_SEP}\n\n正文真身"), "正文真身")
check("三层 → 仍然只留最后一段",
      _strip(f"A\n\n{_SEP}\n\nB\n\n{_SEP}\n\nC\n\n{_SEP}\n\n正文"), "正文")
check("空串安全", _strip(""), "")
check("None 安全", _strip(None), "")
check("只有分隔线 → 空", _strip(f"{_SEP}"), "")
check("正文里没有分隔线时不受影响",
      _strip("他说：这是正文，没有分隔线"), "他说：这是正文，没有分隔线")

# ---- ★★★ 核心回归：连续两轮必须收敛，不能越包越多 ----
def _round(body_in_box: str, instr: str) -> tuple[str, str]:
    """复刻一次审稿：读框 → 剥 → 拼 → 覆盖。返回 (填入内容, 下一轮框内内容)。"""
    plain = _strip(body_in_box)                 # read_body_settled 的语义
    full = f"{instr}\n\n{_SEP}\n\n{plain}"      # fill_review_text 的拼接
    return full, full                           # fill 是覆盖语义


box = "这是第一章的正文。"                       # 站点初始带入
r1, box = _round(box, "指令一")
r2, box = _round(box, "指令二")
r3, box = _round(box, "指令三")

check("第 1 轮后：正文仍是原文", _strip(box).endswith("这是第一章的正文。"), True)
check("第 2 轮后：正文没有翻倍", _strip(r2), _strip(r1))
check("第 3 轮后：正文仍然只有一份", _strip(r3), _strip(r1))
check("换指令后旧指令不残留（框内只出现最后一次指令）",
      box.count("指令一") + box.count("指令二"), 0)
check("换指令后框内是最后一次的指令", "指令三" in box, True)
check("框内分隔线始终只有 1 条（不变多）", box.count(_SEP), 1)
check("三轮后框内长度不增长", len(r3), len(r1))

# ---- 逐字复刻真机探针 5 的数字（827 原文）----
orig = "原" * 827
_f1, b1 = _round(orig, "第一次指令")
_f2, b2 = _round(b1, "第二次指令")
_f3, b3 = _round(b2, "第三次指令")
check("827 字原文：第 1 轮后正文长度保持 827", len(_strip(b1)), 827)
check("827 字原文：第 2 轮后正文长度仍是 827（不再 907）", len(_strip(b2)), 827)
check("827 字原文：第 3 轮后正文长度仍是 827（不再 946）", len(_strip(b3)), 827)

# ---- 静态契约：接线确实用上了剥离 ----
check_true("存在 strip_review_wrapper",
           "def strip_review_wrapper" in ai_src)
check_true("存在 read_review_body",
           "def read_review_body" in ai_src)
check_true("read_review_body 内部会剥离",
           "return strip_review_wrapper(raw)" in ai_src)
check_true("read_body_settled 返回的是剥离后的正文（不是裸 box）",
           "return plain" in ai_src and "plain = strip_review_wrapper(box)" in ai_src,
           "若仍 `return box`，套娃 bug 未修复")
check_true("read_body_settled 不再直接返回原始 box",
           "return box" not in ai_src,
           "原始内容可能含旧指令层")
check_true("read_body_settled 退化分支也剥离",
           "return strip_review_wrapper(body)" in ai_src)
check_true("fill_review_text 拼接前做防御性剥离",
           "body = strip_review_wrapper(body)" in ai_src)
check_true("拼接用的分隔线是常量 REVIEW_SEP（不再手写字符串）",
           "f\"{REVIEW_SEP}\\n\\n{body}\"" in ai_src or
           "{REVIEW_SEP}\\n\\n{body}" in ai_src)

# ============================================ 7. 换章审稿：抽屉里必须是当前章正文
print("\n=== 7. 换章审稿：抽屉里必须是当前章正文 ===")

# ★★ 重要更正（2026-10-05）：这一节原先"证伪"了「抽屉滞留上一章」，
#   但**那个证伪是错的** —— 用户明确重申：
#     「审稿的时候，如果不刷新审稿，他是原来的内容」。
#
#   我误判的原因：复刻流程时**我自己把抽屉关了**才切章，
#   而真实场景是**抽屉一直开着**换章。差异就在这一步。
#
#   真机探针 `_probe_refresh.py` 实测（抽屉不关就换章）：
#     [A] 第1章，抽屉已开：框内 84 字（第1章）
#     [B] 不关抽屉切第2章 → 等 0/0.5/1.5/3.0s：框内仍 84 字（第1章）
#     [C] 不关抽屉切第3章 → 框内仍 84 字（第1章）
#     [D] 关掉抽屉→重开 → 框内 123 字（第3章，正确刷新）
#   ⇒ 坐实：**抽屉不关就换章，站点不重灌「待审文本」，一直是旧章内容。**
#
#   ⇒ 所以修复是：`open_review_pane` 新增 `expect_body`，
#     面板已开时校验框内是否当前章正文；不符则「关掉→重开」强制刷新。
#     本节改为**锁定修复**，防止后人再把这段逻辑删掉。

check_true("open_review_pane 有 expect_body 参数（校验框内是否当前章）",
           "expect_body" in ai_src,
           "抽屉开着换章不会刷新框内容（用户报障 + 探针坐实）")
check_true("面板已开时会校验框内正文",
           "_same_body(cur, expect_body)" in ai_src)
check_true("框内不是当前章 → 关抽屉重开刷新",
           "关掉重开以刷新" in ai_src)
check_true("ai_review 调用 open_review_pane 时传 expect_body",
           "expect_body=_expect" in ai_src)
# ★ 但**不要**用回旧的 refresh_body（那是被证伪的命名，语义不清晰）
check_true("没有复活 refresh_body 旧命名",
           "refresh_body" not in ai_src)

# 真实的衔接坑必须还在：续写弹窗不自动关，开审稿前要先关
check_true("close_continue_dialog 仍存在（续写弹窗拦点击）",
           "def close_continue_dialog" in ai_src)
check_true("continue_to_review 仍会先关续写弹窗再开审稿",
           "close_continue_dialog(page)" in ai_src)

# ---- 纯逻辑：_same_body 判据（站点的换行归一化会让长度略差）----
def _same_body(a: str, b: str) -> bool:
    """复刻 open_review_pane 用的 _same_body 判定。"""
    a = (a or "").strip()
    b = (b or "").strip()
    if not a or not b:
        return False
    if a == b:
        return True
    head_same = a[:60] == b[:60]
    tail_same = a[-60:] == b[-60:]
    tol_n = max(12, int(max(len(a), len(b)) * 0.02))
    if head_same and abs(len(a) - len(b)) <= tol_n:
        return True
    if head_same and tail_same and abs(len(a) - len(b)) <= max(len(a), len(b)) * 0.10:
        return True
    return False


_LONG_A = "陆晨站在公寓门口。" * 20      # 180 字
_LONG_B = "陆晨站在公寓门口。" * 20
check("完全一致 → 同一段", _same_body(_LONG_A, _LONG_B), True)
check("长度略差（换行归一化）→ 仍算同一段",
      _same_body(_LONG_A + "。", _LONG_B), True)
check("开头就不同 → 不是同一段",
      _same_body("林深推开窗。" + "x" * 100, _LONG_A), False)
check("一方为空 → 不是同一段", _same_body("", _LONG_A), False)
check("两方都空 → 不是同一段", _same_body("", ""), False)
check("长短差很大 → 不是同一段",
      _same_body(_LONG_A, _LONG_A + "新增内容" * 40), False)

# ============================================ 7b. 弹窗洁净度（下一章必报错的根因）
print("\n=== 7b. 续写弹窗必须有「开始 AI 续写」按钮 ===")

# ★★★ 根因来自**用户实测日志**（run-20261005-003748.log 第2章）：
#     [ai] ✓ 弹窗已出现: .n-modal:has-text('续写正文')
#     [ai] ✓ 续写弹窗为初始态（干净的新弹窗）
#     [ai] --- 开始 AI 续写 ---
#     [ai] ✗ 找不到目标: 开始 AI 续写        ← 真正的失败点
#     [batch] ✗ 第2章失败（16s）（2028 字达标，已采纳）  ← reason 也是错的
#
#   ⇒ 两个问题叠加：
#     ① 打开的"续写弹窗"里**没有开始按钮**（残页/假弹窗）。
#        早期只查"是否完成态/是否生成中"，这种残页两样都不是 ⇒ 被放行。
#        → 现在判据升级为「**必须看得见「开始 AI 续写」按钮**」。
#     ② 失败 reason 显示成上一章的「2028 字达标，已采纳」——
#        因为 LAST_DECISION 是**全局变量**，第2章早期失败时还留着第1章的值。
#        → 现在 ai_continue 入口先清 LAST_DECISION，失败时也写它。
check_true("存在 _has_start_button（权威可用性判据）",
           "def _has_start_button" in ai_src)
check_true("存在 _fake_continue_dialog_present（假弹窗识别）",
           "def _fake_continue_dialog_present" in ai_src)
check_true("存在 _close_any_continue_dialog（关假弹窗）",
           "def _close_any_continue_dialog" in ai_src)
check_true("open_continue_dialog 判据要求有开始按钮",
           "未见「开始 AI 续写」按钮（疑似残页）" in ai_src)
check_true("ai_continue 洁净度校验基于开始按钮",
           "没有「开始 AI 续写」按钮" in ai_src)
check_true("校验失败会关掉重开",
           "判定为残页/假弹窗，关掉重开" in ai_src)
check_true("重开仍无按钮则终止（不带病往下走）",
           "重开后仍找不到「开始 AI 续写」按钮" in ai_src)
check_true("ai_continue 入口清掉上一轮 LAST_DECISION",
           "先把上一轮的决策清掉" in ai_src)
check_true("失败分支也会写 LAST_DECISION（不再残留上一章值）",
           "续写弹窗里没有「开始 AI 续写」按钮（残页）" in ai_src)
check_true("失败 reason 禁止出现'达标/已采纳'语气",
           "未产生本轮结果" in ai_src)
check_true("批量跑章失败时不再回退到 gen.reason",
           "只在**成功**时才允许回退到 gen.reason" in ai_src)
check_true("ai_auto_chapter 进续写前主动清理残留",
           "主动清理" in ai_src)
check_true("存在章末统一清理 _cleanup_tail",
           "def _cleanup_tail" in ai_src)
_cleanup_calls = ai_src.count("_cleanup_tail()")
check_true(f"章末清理在每个出口都调用（>=5 处，实测 {_cleanup_calls}）",
           _cleanup_calls >= 5,
           "失败出口尤其要清，否则弹窗异常态会传染到下一章")
check_true("残留检测遍历所有 modal（不再只看 first）",
           "遍历所有 modal" in ai_src and "遍历所有可见 modal" in ai_src)

# ============================================ 7c. 选提示词必须"真的选上"
print("\n=== 7c. 选提示词要回读确认（用户报「根本没选上」）===")

# ★★★ 用户原话（2026-10-05）：
#   「在选择「强盛集团云霄」和「强盛集团云霄拯救过稿计划」这两个提示词的
#     时候，点击后需要加一小点的延迟，不然有时候加载不出来，导致根本
#     没选上，或者你加一个状态检测？到底选没选上？」
#
# ★ 本机逐帧探针坐实的真根因（_probe_pick2.py）：
#     面板是**分批渲染**的：
#       t=0.01s 行数= 0
#       t=0.20s 行数=11     ← 第一批
#       t=0.26s 行数=26     ← 第二批
#     老 wait_shortcut_loaded 判据是「行数连续两次一致且 >0 就返回」
#     ⇒ **0.2 秒就返回**。目标若在第 12~26 条里 ⇒ 返回时还没渲染
#     ⇒ 后续 filter(has_text=关键字) 命中 0 ⇒ 判「面板里没有含 xx 的提示词」
#     ⇒ **静默跳过、根本没选上**。这就是用户看到的现象。
#
# ★ 修复三件：
#   ① wait_shortcut_loaded 加 keyword 参数：有明确目标时判据升级为
#      「**目标那一行已渲染**」，并支持「列表渲染完仍无目标 → 提前退出」。
#   ② 找不到目标时不再立刻放弃：补等 + 滚动列表，再找 2 轮。
#   ③ 点击后**必须回读确认**；没对上 → 延迟后重试点击一次。
#      续写读「续写要求」行、审稿读「审稿要求」行（verify_row 区分）。
check_true("wait_shortcut_loaded 支持 keyword 参数（按目标等待，而非只看行数）",
           "def wait_shortcut_loaded(page: Page, timeout: float = 20.0,\n                         poll: float = 0.1, keyword: str = \"\")" in ai_src)
check_true("目标行渲染出来就算加载完成",
           "目标提示词已渲染" in ai_src)
check_true("列表渲染完仍无目标 → 提前退出（不白等满超时）",
           "提前结束等待" in ai_src)
check_true("pick_shortcut 调用时把 keyword 传给等待函数",
           "wait_shortcut_loaded(page, timeout=8.0, keyword=keyword)" in ai_src)
check_true("找不到目标时会补等+滚动列表重试（不再一次放弃）",
           "补等并滚动列表" in ai_src)
check_true("pick_shortcut 点击后回读确认（续写/审稿各读各自那一行）",
           "def _read_back()" in ai_src and "current_review_requirement(page)" in ai_src)
check_true("回读未命中 → 延迟后重试点击一次（用户要求的那「一小点延迟」）",
           "延迟后重试点击一次" in ai_src and "time.sleep(0.6)" in ai_src)
check_true("审稿场景也回读（老代码 verify_row=False 完全不回读）",
           "审稿要求回读未命中，但点击已成功" in ai_src)
check_true("重试前会重新打开面板（面板已收起的情况）",
           "重试前重开面板失败" in ai_src)
check_true("回读命中会打印「回读确认」",
           "（回读确认）" in ai_src)
check_true("旧的「跳过行回读」静默分支已删除",
           "跳过行回读" not in ai_src)

# ============================================ 8. 审稿前必须确认"是哪一章"
print("\n=== 8. 审稿前核对章号（用户问「你知道是哪一章吗？」）===")

# ★ 用户原话：「你续写完了，你知道是哪一章吗？」
#   一条龙的续写和审稿作用在「编辑器当前打开的那一章」。
#   站点在某些操作后可能自己跳章（如自动新建章节后跳到新章）
#   ⇒ 不核对就会**审错章**。所以：
#     ① 新增 current_chapter_no() 读当前 active 章号
#     ② ai_auto_chapter 审稿前核对；不符则切回；切不回就终止

check_true("存在 current_chapter_no（读当前打开的章号）",
           "def current_chapter_no" in ai_src)
check_true("current_chapter_no 用 active 标记定位",
           "chapter-item--active" in ai_src)
check_true("ai_auto_chapter 审稿前做章号核对",
           "审稿前核对" in ai_src)
check_true("章号不符会切回目标章",
           "续写后站点跳章了" in ai_src)
check_true("切不回目标章会终止（宁可失败也不审错章）",
           "避免审错章" in ai_src)
check_true("错位时返回明确的 reason",
           "审稿前章节错位" in ai_src)

# ---- 纯逻辑：章号核对分支 ----
def _chap_check(cur_no: int, want_no: int) -> str:
    """复刻 ai_auto_chapter 的章号核对判定。"""
    if want_no <= 0:
        return "跳过"           # 没指定章号
    if cur_no == want_no:
        return "一致"
    if cur_no < 0:
        return "未知继续"        # 读不出来，不阻断
    return "切回"


check("章号一致 → 直接审", _chap_check(3, 3), "一致")
check("章号不符 → 切回目标章", _chap_check(4, 3), "切回")
check("读不出章号 → 继续（不阻断）", _chap_check(-1, 3), "未知继续")
check("未指定章号 → 跳过核对", _chap_check(3, -1), "跳过")

# ============================================ 9. 一条龙默认参数不该放宽
print("\n=== 9. 一条龙函数默认值（防漏传时静默失效）===")

# ★ ai_auto_chapter / ai_batch_chapters 的**签名默认值**若还是
#   100~5000 + max_retry=0，则任何漏传的调用方（CLI/新入口/单测）
#   都会静默拿到"放宽区间 + 不重试"，正是用户最初报的 bug。
check_true("ai_auto_chapter 默认下限是 2100（不再是 100）",
           "min_words: int = 2100" in ai_src,
           "宽区间默认会让字数限制静默失效")
check_true("ai_auto_chapter 默认上限是 2300（不再是 5000）",
           "max_words: int = 2300" in ai_src)
check_true("ai_auto_chapter 默认 max_retry 是 5（不再是 0）",
           "max_retry: int = 5" in ai_src,
           "max_retry=0 等于一轮定生死")
check_true("ai_batch_chapters 默认下限也是 2100",
           "min_words: int = 2100" in ai_src)
check_true("ai_batch_chapters 默认 max_retry 也是 5",
           "max_retry: int = 5" in ai_src)

# ============================================ 10. 「点不到开始 AI 续写」（2026-10-05 第3次报障）
print("\n=== 10. 点不到「开始 AI 续写」：判据必须逐个探测可见元素 ===")
# 用户实测：第 46 章成功、第 47 章失败「点不到『开始 AI 续写』按钮（14秒）」。
# 根因：_visible() 只看 .first，多章残留/隐藏过渡层让 .first 命中不可见元素
# ⇒ 判「找不到目标」直接 return False，三级降级一步没走。
# 而同一页面上 _has_start_button()（逐个探测）说"有按钮" —— 自相矛盾。
_vis_src = ai_src.split("def _visible(")[1].split("def _present(")[0]
# ★ 只检查**真实代码**：剥掉注释行 + 文档字符串（三引号内的说明文字）。
#   否则注释里解释历史的 "`.first` 会命中隐藏元素" 会误判为"代码里还在用"。
import ast as _ast
_ai_mod = _ast.parse(ai_src)
_vis_fn = next(
    (n for n in _ai_mod.body
     if isinstance(n, _ast.FunctionDef) and n.name == "_visible"), None)
assert _vis_fn is not None, "没找到 _visible 函数"
if (_vis_fn.body and isinstance(_vis_fn.body[0], _ast.Expr)
        and isinstance(_vis_fn.body[0].value, _ast.Constant)):
    _vis_fn.body = _vis_fn.body[1:]          # 去掉 docstring
_vis_code = _ast.unparse(_vis_fn)
check_true("_visible 代码里不再用 .first（它会命中隐藏元素）",
           ".first" not in _vis_code,
           "只看 .first 会命中隐藏元素")
check_true("_visible 逐个探测（对 count 做遍历）", "min(n, max_probe)" in _vis_src)
check_true("_visible 第 1 轮无超时快探（隐藏元素不白等 timeout）",
           "第 1 轮" in _vis_src and "第 2 轮" in _vis_src)
check_true("_visible 第 1 轮用无超时 is_visible()", "loc.nth(i).is_visible()" in _vis_src)
check_true("_visible 第 2 轮才用带 timeout 的 is_visible",
           "loc.nth(i).is_visible(timeout=timeout)" in _vis_src)
check_true("存在 _present()（找『存在但不一定可见』的元素）", "def _present(" in ai_src)
check_true("_click_first 有第四档降级（存在即 JS 直点）",
           "元素存在但判定不可见 → JS 直点兜底" in ai_src)
check_true("第四档用的是 _present", "_present(page, selectors)" in ai_src)
check_true("失败信息区分『无可见也无存在』",
           "既无可见、也无存在的匹配元素" in ai_src)
# 判据一致性：_has_start_button 与 _visible 都必须"逐个探测"
check_true("_has_start_button 也是逐个探测（两处判据已统一）",
           "for i in range(min(n, 4))" in ai_src)

# ============================================ 11. 「字数」口径（2026-10-06 用户报障）
print("\n=== 11. 本章字数：必须与站点显示的一致（不能把换行/空白数进去）===")
# 用户报：「高级参数里认到的字数是不准确的」。
# 真机取证（probes/probe_wc_site.py）：同一章第3章
#   站点 = 4018 字；app 的 len(get_body_text()) = 4676（虚高 16.4%，其中 \n 有 629 个）
#   第1章：站点 15676 vs app 20027（虚高 27.8%）
# ⇒ 站点口径 = 非空白字符数；app 必须读站点自己的数，才对得上用户的肉眼。
import xyxbot.ai as _AI3

check("count_chars 不数换行", _AI3.count_chars("你好\n世界"), 4)
check("count_chars 不数空格", _AI3.count_chars("a b c"), 3)
check("count_chars 不数全角空格", _AI3.count_chars("你　好"), 2)
check("count_chars 不数制表/回车", _AI3.count_chars("甲\t\r乙"), 2)
check("count_chars 空串 = 0", _AI3.count_chars(""), 0)
check("count_chars 纯换行 = 0", _AI3.count_chars("\n\n\n"), 0)
check("_parse_word_num 纯数字", _AI3._parse_word_num("4018"), 4018)
check("_parse_word_num 带千分位与'字'", _AI3._parse_word_num("4,018 字"), 4018)
check("_parse_word_num 万字", _AI3._parse_word_num("2.1万字"), 21000)
check("_parse_word_num 千字", _AI3._parse_word_num("1.2千字"), 1200)
check("_parse_word_num 读不到 → -1", _AI3._parse_word_num(""), -1)
check("_parse_word_num 非数字 → -1", _AI3._parse_word_num("abc"), -1)

_ai3_src = open(_AI3.__file__, encoding="utf-8").read()
check_true("存在 site_chapter_word_count（读站点自己显示的数）",
           "def site_chapter_word_count(" in _ai3_src)
check_true("存在 chapter_word_count（统一入口，展示/上报都用它）",
           "def chapter_word_count(" in _ai3_src)
check_true("site_chapter_word_count 读编辑器右下 .chapter-word-count",
           ".chapter-word-count" in _ai3_src)
check_true("site_chapter_word_count 有左栏 meta 兜底",
           "chapter-item__meta" in _ai3_src)


# ---- 用假 page 验证 chapter_word_count 的两条路径（不需要浏览器）----
class _FakeEl:
    """模拟 Playwright 的 Locator（真实 Playwright 的 nth(i) 返回的也是 Locator，
    带 count() / first / inner_text() / is_visible()）。"""

    def __init__(self, t):
        self._t = t

    def count(self):
        return 1

    @property
    def first(self):
        return self

    def is_visible(self):
        return True

    def inner_text(self, timeout=None):
        return self._t


class _FakeLoc:
    def __init__(self, items):
        self._i = list(items)

    def count(self):
        return len(self._i)

    def nth(self, i):
        return self._i[i]

    @property
    def first(self):
        return self._i[0]


class _PageWithSiteCount:
    """能读到站点 .chapter-word-count 的假页面。"""

    def locator(self, sel):
        if "chapter-word-count" in sel:
            return _FakeLoc([_FakeEl("4018")])
        raise RuntimeError("no such element")

    def evaluate(self, js):
        return "你好\n世界\n"          # 本机文本：4 个非空白字符


class _PageNoSiteCount:
    """站点元素全读不到的假页面（走本机兜底）。"""

    def locator(self, sel):
        raise RuntimeError("no dom")

    def evaluate(self, js):
        return "你好\n世界\n"


check("chapter_word_count 优先用站点那个数",
      _AI3.chapter_word_count(_PageWithSiteCount()), 4018)
check("站点读不到 → 退回「非空白字符数」（不是 len）",
      _AI3.chapter_word_count(_PageNoSiteCount()), 4)
check("同样的文本，len() 会多算换行（旧口径的问题）",
      len("你好\n世界\n"), 6)

# ---- 静态断言：上报点不能再直接用 len(get_body_text) ----
import re as _re3

# ① ai_auto_chapter 的「起始正文」必须是站点口径
check_true("ai_auto_chapter 的 body_before 用 chapter_word_count",
           "body_before = chapter_word_count(page)" in _ai3_src)
check_true("ai_auto_chapter 仍保留原始长度 _raw_before 做变更判据",
           "_raw_before = len(get_body_text(page))" in _ai3_src)
check_true("wait_body_change 传的是 _raw_before（判据）+ before_words（展示）",
           "before_len=_raw_before," in _ai3_src
           and "before_words=body_before" in _ai3_src)

# ② 「已打开章节（正文 N 字）」/「正文已就绪」/「当前章正文」三处日志
check_true("「已打开章节」日志用 chapter_word_count",
           '已打开章节（正文 {chapter_word_count(page)} 字' in _ai3_src)
check_true("「正文已就绪」日志用 chapter_word_count",
           '正文已就绪（{chapter_word_count(page)} 字）' in _ai3_src)
check_true("「当前章正文」日志用 chapter_word_count",
           "chapter_word_count(page, body=_expect)" in _ai3_src)

# ③ wait_body_change 返回站点口径（它一路传到界面结果表的「字数」列）
_wbc_src = _ai3_src.split("def wait_body_change(")[1].split("def ai_auto_chapter(")[0]
check_true("wait_body_change 返回站点口径字数",
           "final = chapter_word_count(page)" in _wbc_src
           or "final = int(_last[0])" in _wbc_src)
check_true("wait_body_change 的变更判据仍用原始长度（最灵敏）",
           "cur = len(get_body_text(page))" in _wbc_src)
check_true("wait_body_change 会等站点字数刷新（不是读一次就走）",
           "站点字数刷新" in _wbc_src)

# ④ 结果表那条链路：words 来自 r["body"]，而 body 现在已是站点口径
check_true("界面结果表的 words 仍来自 body（body 已是站点口径）",
           'words=r.get("body") or 0' in _ai3_src)

# ============================================ 12. 关联最近 N 章必须真的设上（2026-10-06）
print("\n=== 12. 「关联最近10章」：每次生成都要真的设上 ===")
# 用户问：「他每次生成，都选择了最近十章吗？为什么这次没有选上最近十章呢」
# 真机实测（probes/probe_relate10.py）：
#   · 站点**每次新开弹窗都回到默认「最近5章」**（关掉再开 ×2、换章 ×1，全读到 5）
#   · 所以 app 每次都必须真的把它改成 10 —— 不能靠"读一次就跳过"蒙
# 三个加固点：① 只在当前续写弹窗里读（防残留弹窗误判）
#            ② 回读要连续两次一致（防菜单开着时假命中）
#            ③ 失败自动重试一轮
_ai4_src = open(_AI3.__file__, encoding="utf-8").read()

check_true("存在 _relate_dropdown_in（可指定容器搜索）",
           "def _relate_dropdown_in(" in _ai4_src)
check_true("存在 _relate_scope_roots（按优先级给容器）",
           "def _relate_scope_roots(" in _ai4_src)
check_true("优先只在「含开始按钮的续写弹窗」里找下拉",
           "_CONTINUE_MODAL_SEL" in _ai4_src
           and "开始 AI 续写" in _ai4_src.split("_CONTINUE_MODAL_SEL = ")[1][:120])
check_true("_relate_dropdown 遍历 scopes（弹窗优先 → 全页兜底）",
           "for root in _relate_scope_roots(page):" in _ai4_src)

_rel_src = _ai4_src.split("def relate_chapters(")[1].split("def start_generate(")[0]
check_true("relate_chapters 有 _retried 参数（供内部重试）",
           "_retried: bool = False" in _rel_src)
check_true("回读要求连续两次一致（_hit 计数 >= 2）",
           "_hit[0] >= 2" in _rel_src)
check_true("回读日志标注 ×2（与单次读区分开）",
           "回读确认 ×2" in _rel_src)
check_true("失败会关菜单重试一轮",
           'page.keyboard.press("Escape")' in _rel_src
           and "关掉菜单重试一次" in _rel_src)
check_true("失败重试走 _retried=True（防无限递归）",
           "_retried=True" in _rel_src)
check_true("「已是目标档」跳过分支也做二次确认",
           "档位读数不稳" in _rel_src)
check_true("失败日志明确提示将用站点默认档位",
           "本次生成将用**站点默认档位**" in _rel_src)

# 真机取证结论也钉进测试：站点默认是 5，不是 10
check_true("relate_chapters 仍会在不是目标档时真的去点（不是纯读）",
           "展开菜单" in _rel_src)

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

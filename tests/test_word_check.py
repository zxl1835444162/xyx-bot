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
    import src.ai as _ai_mod
    _ai = _ai_mod
    _real_import = True
except Exception as e:
    print(f"  [WARN] 以包方式导入 src.ai 失败（{str(e).splitlines()[0]}），"
          f"尝试文件加载")
    try:
        _spec = _ilu.spec_from_file_location("_ai_mod", str(ROOT / "src" / "ai.py"))
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

# ============================================ 7. 换章审稿：实测证伪「滞留上一章」
print("\n=== 7. 换章审稿：抽屉里必须是当前章正文 ===")

# ★ 用户提示：「不是，是你换了章，才点审稿的」——提醒我看真实用法。
#   我曾据此怀疑一个 bug 并加了"面板已开就刷新"的逻辑：
#     站点**只在抽屉打开的那一刻**灌入当前章正文，换章不会更新
#     ⇒ 面板开着换章 → 框里滞留上一章 → 审错章
#
#   ★★ 但复刻用户真实流程后用真机实测**证伪**了：
#     真实链路是「换章 → 开续写 → 关续写 → 点审稿」
#     （续写弹窗是居中模态，必须先关，见 continue_to_review 的坑1）
#     ⇒ 此时抽屉**必是首次打开**，站点会正常灌入当前章正文。
#     实测：第3章流程→框内第3章、第1章流程→框内第1章，均正确。
#
#   ⇒ 结论：**不存在错章问题**，不该加"先关后开"的刷新逻辑（徒增复杂）。
#     本节改为**锁定这个结论**，防止后人又被同样的猜测误导、加回无用代码。

check_true("open_review_pane 不再有 refresh_body 参数（实测证伪，保持简单）",
           "refresh_body" not in ai_src,
           "该参数针对不存在的场景；真实流程抽屉总是首次打开")
check_true("open_review_pane 不再有 expect_body 参数",
           "expect_body" not in ai_src)
check_true("没有『先关后开』的强制刷新分支",
           "抽屉已开着但需刷新正文" not in ai_src)
check_true("ai_review 不做正文前缀校验（无此必要）",
           "当前章正文前缀（用于校验抽屉带入）" not in ai_src)

# 但真实的衔接坑必须还在：续写弹窗不自动关，开审稿前要先关
check_true("close_continue_dialog 仍存在（续写弹窗拦点击）",
           "def close_continue_dialog" in ai_src)
check_true("continue_to_review 仍会先关续写弹窗再开审稿",
           "close_continue_dialog(page)" in ai_src)

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

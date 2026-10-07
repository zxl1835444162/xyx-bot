"""对外流程：续写 / 审稿 / 一条龙 / 批量跑章。

本文件由 `xyxbot/ai.py` 拆分而来（Phase C1）。拆分时按 AST 依赖做了拓扑排序，
所以每个模块只 import 排在自己前面的模块，不存在循环引用。
"""

from __future__ import annotations

from xyxbot import actions as A
from xyxbot.waiting import wait_gone, wait_until, wait_visible
from playwright.sync_api import Page
from typing import Callable, List, Optional
import re
import time

from xyxbot.ai.body import chapter_word_count, editor_ready, get_body_text, select_all_body, wait_body_change
from xyxbot.ai.chapters import _chapter_ready, chapter_numbers, current_chapter_no, ensure_chapter, open_chapter
from xyxbot.ai.current import current_shortcut
from xyxbot.ai.dialog import _close_any_continue_dialog, _close_stale_result, _fake_continue_dialog_present, _has_start_button, _stale_result_present, close_continue_dialog, continue_dialog_open, open_continue_dialog
from xyxbot.ai.elements import _shot, cancel_requested
from xyxbot.ai.generate import gen_finished, gen_in_progress, generate_with_word_check, get_gen_word_count, start_generate
from xyxbot.ai.model import fill_plot, select_model
from xyxbot.ai.relate import relate_chapters
from xyxbot.ai.review import close_review_pane, fill_review_text, open_review_pane, pick_review_requirement, read_body_settled, replace_review_result, start_review, strip_review_wrapper, wait_review_done
from xyxbot.ai.selectors import MODEL_CARD_HINT, REVIEW_PANE_SEL
from xyxbot.ai.shortcuts import pick_shortcut

__all__ = ["ai_auto_chapter", "ai_batch_chapters", "ai_continue", "ai_review"]

LAST_DECISION: Optional[dict] = None

def ai_continue(page: Page,
                plot: str = "",
                model: str = "细腻版",
                associate: str = "正常",
                relate_count: int = 10,
                shortcut: str = "",
                shortcut_index: int = 0,
                shortcut_search: bool = False,
                start: bool = True,
                wait_dialog: float = 3.0,
                auto_accept: bool = False,
                min_words: int = 2100,
                max_words: int = 2300,
                max_retry: int = 5,
                gen_timeout: float = 240.0,
                hard_min: int = 0,
                best_effort: bool = True) -> bool:
    """完整流程：开弹窗 → 选快捷选项 → 选模型 → 填剧情 → 关联章节 → 开始续写
                →（可选）按字数自动「采纳 / 重新生成」。

    Args:
        plot:         后续剧情文本（前缀+内容+后缀 已由调用方拼好）
        model:        模型分类，默认「细腻版」
        associate:    联想能力，「正常」/「关闭」
        relate_count: 关联最近几章，默认 10
        shortcut:     ★ 快捷选项（提示词）关键词，如「强盛集团云霄」。
                      为空则不动这一项，保持站点默认。
        shortcut_index: 关键词命中多个时选第几个
        shortcut_search: 选之前先在面板搜索框里搜一下
        start:        是否点「开始 AI 续写」
        auto_accept:  ★ 是否开启「按字数自动决策」：
                        生成字数 ∈ [min_words, max_words] → 采纳使用
                        否则 → 重新生成（最多 max_retry 次）
        min_words:    字数下限（含）
        max_words:    字数上限（含）
        max_retry:    最多重新生成几次
        gen_timeout:  每次生成最多等多久（秒）
        hard_min:     ★ 硬下限（保底）：重试用完若当轮 ≥ hard_min 仍然采纳。
                      0 = 关闭。适合「提示词天生偏短」的场景，防止空转。
        best_effort:  ★ 重试耗尽仍未入区间时，是否采纳最后一轮（尽力而为）
    """
    global LAST_DECISION          # ★ 必须在函数体最前面声明
    # ★★★ 2026-10-05（用户实测日志定位）：**先把上一轮的决策清掉**。
    #   否则本轮若在早期就失败（如找不到「开始 AI 续写」），
    #   `ai_auto_chapter` 拿到的 `LAST_DECISION` 还是**上一章的**，
    #   于是失败原因被显示成上一章的「2028 字达标，已采纳」—— 完全误导。
    #   用户日志铁证：
    #     第1章 →「2028 字达标，已采纳」（正确）
    #     第2章失败 →「2028 字达标，已采纳」（✗ 这是第1章的值！）
    LAST_DECISION = None
    print("=" * 58)
    print("  AI 续写正文")
    print(f"    模型     = {model}")
    print(f"    联想能力 = {associate}")
    print(f"    关联章节 = 最近 {relate_count} 章")
    if shortcut:
        print(f"    快捷选项 = {shortcut}")
    print(f"    剧情长度 = {len(plot)} 字")
    if auto_accept:
        print(f"    自动采纳 = 是（{min_words}~{max_words} 字，最多重生成 {max_retry} 次）")
    print("=" * 58)

    if not open_continue_dialog(page, wait=wait_dialog):
        LAST_DECISION = {"ok": False, "words": -1, "tries": [], "rounds": 0,
                         "reason": "续写弹窗打不开"}
        return False

    # ⓪-0 ★★ 弹窗洁净度校验（2026-10-05 新增，定位用户报「下一章点续写就报错」）
    #   用户原话：「生成某一章没事，下一章一点『AI续写正文』就出错」
    #              + 「停留在续写界面」。
    #
    #   ★★★ 用户实测日志（run-20261005-003748.log，第2章）给出的**真实根因**：
    #     ```
    #     [ai] ✓ 弹窗已出现: .n-modal:has-text('续写正文')
    #     [ai] ✓ 续写弹窗为初始态（干净的新弹窗）
    #     ...
    #     [ai] ✗ 找不到目标: 开始 AI 续写       ← 失败点
    #     ```
    #     ⇒ 打开的弹窗**没有「开始 AI 续写」按钮**（是个残页/假弹窗）。
    #       前几版校验只查"是否完成态/是否生成中"，这种残页**两样都不是**，
    #       所以被判定为"初始态 ✅"放行 —— 校验不够严。
    #
    #   ⇒ 现在的权威判据：**必须真的看得见「开始 AI 续写」按钮**。
    #     没有 → 关掉重开；重开仍没有 → 明确失败（绝不再带上"找不到按钮"往下走）。
    if not _has_start_button(page):
        print("[ai] ⚠ 打开的续写弹窗**没有「开始 AI 续写」按钮**"
              f"（完成态={gen_finished(page)} 生成中={gen_in_progress(page)}）"
              "→ 判定为残页/假弹窗，关掉重开")
        _close_stale_result(page)
        _close_any_continue_dialog(page)
        if not open_continue_dialog(page, wait=wait_dialog):
            print("[ai] ✗ 重开续写弹窗失败")
            LAST_DECISION = {"ok": False, "words": -1, "tries": [], "rounds": 0,
                             "reason": "续写弹窗打不开（重开失败）"}
            return False
        if not _has_start_button(page):
            print("[ai] ✗ 重开后仍找不到「开始 AI 续写」按钮"
                  "→ 终止（继续只会重复'找不到目标'）")
            _shot(page, "ai_continue_no_start_btn")
            LAST_DECISION = {"ok": False, "words": -1, "tries": [], "rounds": 0,
                             "reason": "续写弹窗里没有「开始 AI 续写」按钮（残页）"}
            return False
        print("[ai] ✓ 续写弹窗已刷新，含「开始 AI 续写」按钮")
    else:
        print("[ai] ✓ 续写弹窗可用（含「开始 AI 续写」按钮）")

    # ⓪ ★ 选快捷选项（提示词）—— 必须在填剧情之前，
    #    因为换提示词可能会重置「续写要求」框里的内容
    if shortcut and shortcut != "跳过":
        before = current_shortcut(page)
        if shortcut in (before or ""):
            print(f"[ai] 快捷选项已是「{shortcut}」，跳过")
        else:
            pick_shortcut(page, keyword=shortcut, index=shortcut_index,
                          search_first=shortcut_search)

    # ① 选模型 + 联想能力（顺序：分类 → 模型卡片 → 联想能力 → 使用此模型）
    select_model(page, model=model, associate=associate)

    # ② 填后续剧情
    if plot.strip():
        fill_plot(page, plot)
    else:
        print("[ai] 未提供剧情文本，跳过填写")

    # ③ 关联最近 N 章
    # ★★ 必须检查返回值（2026-10-04）：旧代码忽略它，所以"关联章节没设上"
    #    这件事在日志里只是一行 ✗，流程照跑 —— 模型看不到前文，
    #    生成质量下降却没有任何告警。这是内容质量事故，必须显式警告。
    if relate_count and relate_count > 0:
        if not relate_chapters(page, count=relate_count):
            print(f"[ai] ⚠⚠ 警告：关联章节**未设置成功**（目标 最近{relate_count}章）！"
                  f"本次生成可能看不到前文，内容连贯性会变差。")
    else:
        print("[ai] relate_count<=0，跳过关联章节")

    _shot(page, "ai_ready")

    if not start:
        print("[ai] start=False，停在弹窗前（调试模式）")
        return True

    # ④ 开始
    ok = start_generate(page)
    if not ok:
        LAST_DECISION = {"ok": False, "words": -1, "tries": [], "rounds": 0,
                         "reason": "点不到「开始 AI 续写」按钮"}
        return False
    print("[ai] ✓ 已触发 AI 续写，等待生成 …")

    # ⑤ ★ 按字数自动决策
    if auto_accept:
        r = generate_with_word_check(page, min_words=min_words,
                                     max_words=max_words,
                                     max_retry=max_retry,
                                     gen_timeout=gen_timeout,
                                     hard_min=hard_min,
                                     best_effort=best_effort)
        print(f"[ai] 字数决策结果：{r['reason']}"
              f"（各轮字数 {r['tries']}）")
        LAST_DECISION = r          # ★ 供 UI 显示细节（已在上方 global）
        return r["ok"]

    LAST_DECISION = None
    return True

def ai_review(page: Page,
              text: str = "",
              model: str = "智慧版",
              model_card_name: str = "智慧版-6A",
              model_card_hint: str = "更懂作者意图，能稳定抓住风格",
              associate: str = "正常",
              requirement: str = "",
              req_tab: str = "快捷选项",
              instruction: str = "",
              open_chapter: str = "",
              chapter_index: int = 0,
              start: bool = True,
              wait_pane: float = 0.6,
              wait_done: bool = False,
              done_timeout: float = 600.0,
              replace: bool = False,
              select_all: bool = True) -> bool:
    """完整流程：开章节 → 开审稿面板 → 选模型 → 填待审文本 → 选审稿要求
                → 点生成 →（可选）等完成 →（可选）全选 →（可选）替换落盘。

    ★ 用户指定配置（2026-10-03）：
        模型     = 智慧版 → **智慧版-6A**
        联想能力 = **正常（0.7）**
        审稿要求 = 快捷选项里那句「强盛集团云霄拯救过稿计划（智慧5.6内测专属，审稿前10章）」
      ★ 审稿流程完整链路（用户明确要求）：
        ① 打开章节（否则正文为空）
        ② 点「生成」→ 等生成完（几分钟很正常）
        ③ ★ **全选正文** → ② 点「替换 / 插入」
           （不全选就变成「插入」，原文还在 → 前后拼接）

    Args:
        text:            待审文本；**给了就完全覆盖**（优先级最高）
        model:           模型分类，默认「智慧版」
        model_card_name: ★ 具体模型卡片名（分类与卡片名不同！），默认「智慧版-6A」
        model_card_hint: 用来精确定位是哪张模型卡（默认 6A 的描述）
        associate:       联想能力，「正常」= 0.7
        requirement:     审稿要求关键词（文字定位）
        req_tab:         「快捷选项」/「自定义」/「更多」
        instruction:     ★ 指令模板/追加要求，会跟当前章正文**拼在一起**
                         填进「待审文本」（类似续写的指令模板用法）
        open_chapter:    ★ 先打开哪一章（标题关键词，如「第2章」）；
                         留空则按 chapter_index 选第一个
        chapter_index:   open_chapter 为空时选第几个章节项
        start:           是否点「生成」
        wait_pane:       点开后等多久
        wait_done:       ★ 是否等审稿生成完成（等「替换 / 插入」出现）
        done_timeout:    ★ 等生成的最长时间（默认 600s；审稿慢，给足）
        replace:         ★ 是否在完成后点「替换 / 插入」落盘到正文
                         （需要 wait_done=True 才有意义）
        select_all:      ★ 点「替换」之前是否**全选正文**（默认 True）。
                         不选中的话「替换 / 插入」会变成**插入**，
                         原文保留 → 结果跟原稿前后拼接。

    Returns:
        bool 是否走完全流程；replace=True 时返回「替换」是否点到
    """
    print("=" * 58)
    print("  AI 审稿")
    print(f"    模型     = {model} → {model_card_name}")
    print(f"    联想能力 = {associate}")
    print(f"    审稿要求 = {requirement or '(不改)'}（{req_tab}）")
    if instruction:
        print(f"    追加指令 = {len(instruction)} 字（与正文拼接）")
    print(f"    待审文本 = {'（显式覆盖）' if text else ('（沿用页面自带）' if not instruction else '（正文+指令）')}")
    if wait_done:
        print(f"    等生成   = 是（最多 {done_timeout:.0f}s）")
    if replace:
        print(f"    替换落盘 = 是（先全选：{'是' if select_all else '否'}）")
    print("=" * 58)

    # ⓪ ★ 先打开章节（否则正文区为空，待审文本也是空的）
    #    ★ 不能靠 editor_ready 判断——`.tiptap.ProseMirror` 一直存在（空壳），
    #      必须用 need_text=True 看正文是否真有内容。
    if not editor_ready(page, need_text=True):
        open_chapter(page, which=open_chapter, index=chapter_index)
        # ★★ 修正（2026-10-04）：切完章必须**等正文真的渲染出来**再往下。
        #    原实现切完章节就直接开抽屉，此时编辑器可能还在重渲染，
        #    后面 fill_review_text 拼接时读到**空正文**或**上一章的旧正文**
        #    —— 这正是用户说的「有时候出现差错」。
        read_body_settled(page, timeout=8.0)
    else:
        print(f"[ai] 正文已就绪（{chapter_word_count(page)} 字），跳过打开章节")

    # ① 打开审稿面板（右侧抽屉）
    #    ★★ 修正（2026-10-05）：必须**校验框内是当前章正文**，不符则关掉重开。
    #      用户报障 + 探针坐实：抽屉**开着**换章时，站点不会重灌「待审文本」，
    #      框里一直是旧章内容 ⇒ 审错章。
    #      （我先前误判为"不存在"，是因为复刻流程时自己关了抽屉 —— 见
    #        `open_review_pane` 的详细说明。）
    #      一条龙阶段三走到这里时抽屉可能是：
    #        · 首开（自己关过）→ 站点正常灌当前章 ⇒ 校验通过
    #        · 仍然开着（用户手动开过 / 上一章残留）→ 校验失败 ⇒ 关掉重开
    _expect = strip_review_wrapper(get_body_text(page))
    if _expect:
        print(f"[ai] 当前章正文 {chapter_word_count(page, body=_expect)} 字"
              " → 开抽屉时会校验框内是否一致")
    else:
        print("[ai] ⚠ 读不到当前章正文 → 开抽屉时不校验"
              "（退化为旧行为，站点首开一般会正常灌入）")
    if not open_review_pane(page, wait=wait_pane, expect_body=_expect):
        return False

    # ② 选模型
    #    ★★ 关键（2026-10-03 实测）：模型选择弹窗是**根级
    #       `.n-modal.model-picker-modal`**，跟审稿抽屉**平级**、不在抽屉里！
    #       所以：
    #         container      = 审稿抽屉（去那儿点开模型下拉）
    #         read_container = ".n-modal"（模型弹窗本体 / 回读模型名）
    #       （之前把 container 传成抽屉，导致
    #        `{抽屉} button:has-text('智慧版')` 找不到分类而失败。）
    select_model(page, model=model, associate=associate,
                 container=REVIEW_PANE_SEL,
                 read_container=".n-modal",
                 target=model_card_name,
                 card_hint=model_card_hint)

    # ③ 待审文本（显式覆盖 / 正文+指令拼接 / 沿用自带）
    #    ★★ 修正（2026-10-04）：原来**丢弃返回值** —— 待审文本填失败也照样
    #       往下走，结果是拿"页面自带内容"或空内容去审稿，用户看到的就是
    #       「有时候审的不对」。现在失败直接终止并说明原因。
    if not fill_review_text(page, text, instruction=instruction):
        print("[ai] ✗ 待审文本填写失败 → 终止审稿（继续会审到空/错内容）")
        _shot(page, "ai_review_fill_failed")
        return False

    # ④ 审稿要求（先切 tab，再选提示词）
    if requirement:
        pick_review_requirement(page, keyword=requirement, tab=req_tab)

    if not start:
        print("[ai] start=False，停在「生成」前（调试模式）")
        return True

    # ⑤ 点「生成」
    if not start_review(page):
        return False

    # ⑥ ★ 等审稿跑完（几分钟很正常，耐心等）
    if wait_done:
        if not wait_review_done(page, timeout=done_timeout):
            return False
    elif not replace:
        # 不等也不替换 → 到「已触发生成」就算成功（老行为）
        return True

    # ⑦ ★ 全选正文（★ 否则「替换 / 插入」会变成「插入」，原文保留）
    if replace and select_all:
        select_all_body(page)

    # ⑧ ★ 点「替换 / 插入」把结果落进正文
    if replace:
        return replace_review_result(page)

    return True

def ai_auto_chapter(page: Page,
                    # ---- 续写参数 ----
                    plot: str = "",
                    gen_model: str = "细腻版",
                    gen_associate: str = "正常",
                    relate_count: int = 10,
                    shortcut: str = "",
                    shortcut_index: int = 0,
                    shortcut_search: bool = False,
                    min_words: int = 2100,      # ★ 与 ui/defaults.py 一致
                    max_words: int = 2300,
                    max_retry: int = 5,
                    hard_min: int = 0,
                    best_effort: bool = True,
                    gen_timeout: float = 300.0,
                    # ---- 衔接参数 ----
                    close_dialog: bool = True,
                    settle: float = 2.0,
                    # ---- ★ 前置准备（流程开始前）----
                    prepare: bool = False,
                    prepare_app=None,
                    # ---- 审稿参数 ----
                    do_review: bool = True,
                    review_model: str = "智慧版",
                    review_card: str = "智慧版-6A",
                    review_card_hint: str = "",
                    review_associate: str = "正常",
                    review_req: str = "",
                    req_tab: str = "快捷选项",
                    review_instruction: str = "",
                    review_wait: float = 0.6,
                    review_done_timeout: float = 600.0,
                    replace: bool = True,
                    select_all: bool = True,
                    # ---- ★ 指定章节（批量跑章用）----
                    chapter: str = "") -> dict:
    """★★ 串起来跑：「AI 续写 → 采纳 → 关弹窗 → 等正文 → AI 审稿 → 替换」。

    这是用户要的**从 0 走完整一条章**的流程：
      ① 打开续写弹窗 → 选快捷选项/模型/联想 → 填剧情 → 关联章节 → 开始生成
      ② 按字数自动决策（默认 2100~2300，超了会重新生成）
      ③ ★ 关掉续写弹窗（否则模态拦截后续点击）
      ④ ★ 等正文真正写进编辑器
      ⑤ 打开审稿抽屉 → 选模型/联想/审稿要求 →（可选）追加提示词
      ⑥ 生成 → 等完成 → 全选正文 → 替换落盘

    ★ 关于"一条龙"的衔接正确性（2026-10-04 复刻真实流程实测）：
      阶段二 `close_continue_dialog()` → 阶段三 `ai_review()` 正是用户描述的
      「续写完了 → 关掉续写 → 点审稿」链路。此时抽屉**首次打开**，
      站点会把**当前章**（阶段一打开的那一章）正文灌进「待审文本」框，
      且 `ai_review` 的 ⓪ 步因正文已就绪而**不会切章** ⇒ 审的正是刚续写的章。
      实测确认无误。

    Args:
        plot:          后续剧情文本
        gen_model:     续写模型（细腻版）
        gen_associate: 续写联想能力
        relate_count:  关联最近几章
        shortcut:      续写「快捷选项」关键词
        min_words/max_words: ★ 采纳字数区间（默认 2100~2300，同 ui/defaults.py）
        max_retry:     ★ 超区间时最多重新生成几次（默认 5）
        hard_min:      保底采纳下限（0=关）
        best_effort:   重试耗尽仍采纳最后一轮
        gen_timeout:   单轮生成最长等待
        close_dialog:  ★ 续写后是否关弹窗（默认 True，必须）
        settle:        关弹窗后额外静置秒数
        do_review:     ★ 是否继续审稿（False 则只做续写部分）
        review_model / review_card / review_card_hint / review_associate /
        review_req / req_tab / review_instruction: 审稿参数（同 ai_review）
        review_wait:   打开审稿面板后等待
        review_done_timeout: 等审稿完成的最长秒数
        replace / select_all: 是否替换落盘 / 替换前全选

    Returns:
        dict 各阶段结果：{"gen": {...}, "body": int, "review": bool}
    """
    print("=" * 58)
    print("  ★ AI 自动走一章：续写 → 采纳 → 审稿 → 替换")
    print("=" * 58)

    result = {"gen": None, "body": -1, "review": False,
              "ok": False, "reason": ""}

    def _cleanup_tail() -> None:
        """★★ 章末统一清理（2026-10-05）：把续写相关弹窗清干净。

        为什么要做成函数、并在**每个 return 前**都调：
          · 用户实测日志显示：第1章结束后没清续写结果页 ⇒ 第2章一开就
            「续写弹窗=True」但"没有开始按钮" ⇒ `找不到目标: 开始 AI 续写`
            ⇒ 「本章没事、下一章必报错」。
          · **失败时更要清**（失败往往正是弹窗卡在异常态），
            否则错误会一路传染到后面每一章。
        全程吞异常，绝不影响主流程返回。
        """
        try:
            if _stale_result_present(page):
                print("[auto] 收尾：清理续写结果页（防污染下一章）")
                _close_stale_result(page)
            if continue_dialog_open(page):
                print("[auto] 收尾：关闭续写弹窗")
                close_continue_dialog(page)
            if _fake_continue_dialog_present(page):
                print("[auto] 收尾：关闭残留的续写弹窗壳")
                _close_any_continue_dialog(page)
        except Exception as _e:
            print(f"[auto] 收尾清理异常（忽略）：{_e}")

    # ================= 阶段零：流程准备（可选）=================
    #  ★ 用户需求（2026-10-03）：一条龙之前先做「打开网站 + 保存 cookie/缓存」。
    #    UI 里已经单独给了「① 打开网站并保存」按钮；这里提供程序化入口，
    #    方便 CLI / 任务直接传 prepare=True。
    if prepare:
        print("\n" + "-" * 58)
        print("  【阶段零】流程准备（打开网站 → 保存 cookie/缓存）")
        print("-" * 58)
        try:
            from . import login as _L
            app = prepare_app
            if app is None:
                # 没有 App 就跳过（prepare 需要 app.context 才能导 state）
                st = _L.is_ready()
                print(f"[auto] 未提供 App，仅做本地检查：{st['message']}")
            else:
                r0 = _L.prepare_session(app, save=True, auto=True,
                                        wait_seconds=0, interactive=True)
                if not r0["ok"]:
                    print(f"[auto] ✗ 准备未完成：{r0['message']}")
                    result["prepare"] = r0
                    result["reason"] = f"流程准备未完成：{r0['message']}"
                    return result
                result["prepare"] = r0
                print("[auto] ✓ 准备就绪")
        except Exception as e:
            print(f"[auto] ⚠ 准备阶段异常（忽略，继续）：{e}")

    # ---- 记录采纳前正文（用来判断正文真的变了） ----
    if not editor_ready(page, need_text=True):
        # ★★ 根因修复（2026-10-03）：
        #   之前 `else: open_chapter(page)`（无参）会打开「倒序列表第0个 = 最新章」，
        #   导致「第1章的内容被写进第4章」这种错位。
        #   现在：
        #     - 指定了 chapter → 打开它
        #     - 没指定 → 打开「第1章」（最小章号），绝不切到最新章
        if chapter:
            open_chapter(page, which=chapter)
        else:
            nos = chapter_numbers(page)
            first = min(nos) if nos else 1
            print(f"[auto] 未指定章节，打开第{first}章（最小章号，避免切到最新章）")
            open_chapter(page, which=f"第{first}章")
    # ★★ 两个口径分开（2026-10-06）：
    #   · _raw_before = 原始长度（含换行）→ 唯一用途：给 wait_body_change
    #     判「正文变了没」（最灵敏，不受口径影响）
    #   · body_before = **站点口径字数** → 唯一用途：展示 / 上报
    #     （老代码把 len(get_body_text()) 当字数用，实测虚高 16%~27%）
    _raw_before = len(get_body_text(page))
    body_before = chapter_word_count(page)
    print(f"[auto] 起始正文：{body_before} 字")

    # ================= 阶段一：续写 =================
    print("\n" + "-" * 58)
    print("  【阶段一】AI 续写正文")
    print("-" * 58)

    # ★★ 进入续写前的**状态诊断**（2026-10-05 新增，定位「下一章点续写就报错」）
    #   用户报：「生成某一章没事，下一章一点 AI 续写正文就出错，
    #            提到'字数'、'已满足'之类」。
    #   最可疑的路径：上一章的残留弹窗/结果页没清干净 ⇒
    #     gen_finished 一进来就是 True ⇒ wait_generation 立刻返回
    #     ⇒ 拿旧字数当本轮结果 ⇒ 去点不存在的「采纳使用」。
    #   把这几项状态**显式打出来**，下次复现时日志里就有证据。
    try:
        _diag_gen_fin = gen_finished(page)
        _diag_stale = _stale_result_present(page)
        _diag_dlg = continue_dialog_open(page)
        _diag_start_btn = _has_start_button(page)
        _diag_wc = get_gen_word_count(page)
        print(f"[auto][diag] 进入续写前状态："
              f"结果页={_diag_gen_fin} 残留={_diag_stale} "
              f"续写弹窗={_diag_dlg} 开始按钮={_diag_start_btn} "
              f"读到的字数={_diag_wc} "
              f"| 区间={min_words}~{max_words} 重试={max_retry}")

        # ★★★ 主动清理（2026-10-05，用户实测日志定位）：
        #   用户第2章日志：进入时「续写弹窗=True」但里面**没有开始按钮**
        #   ⇒ 上一章残留物没清干净 ⇒ 后面 start_generate「找不到目标」。
        #   这里在进续写之前**主动清一次**：
        #     · 完成态结果页 → 关掉（_close_stale_result）
        #     · 有续写弹窗字样但没有「开始 AI 续写」按钮 → 假弹窗，关掉
        if _diag_gen_fin or _diag_stale:
            print("[auto][diag] ⚠ 进入时就看到'完成态'结果页 → 主动关掉"
                  "（这是上一章残留，留着会污染本轮判定）")
            _close_stale_result(page)
        if _diag_dlg and not _diag_start_btn:
            print("[auto][diag] ⚠ 进入时有一个'续写弹窗'但**没有开始按钮**"
                  "（假弹窗/残页）→ 主动关掉")
            _close_any_continue_dialog(page)
            if _fake_continue_dialog_present(page) or continue_dialog_open(page):
                print("[auto][diag] ⚠ 关不干净 → 再补一次")
                _close_stale_result(page)
                _close_any_continue_dialog(page)
    except Exception as _e:
        print(f"[auto][diag] 状态诊断失败（忽略）：{_e}")

    gen_ok = ai_continue(
        page,
        plot=plot, model=gen_model, associate=gen_associate,
        relate_count=relate_count, shortcut=shortcut,
        shortcut_index=shortcut_index, shortcut_search=shortcut_search,
        start=True, auto_accept=True,
        min_words=min_words, max_words=max_words,
        max_retry=max_retry, gen_timeout=gen_timeout,
        hard_min=hard_min, best_effort=best_effort)
    result["gen"] = dict(LAST_DECISION) if LAST_DECISION else {"ok": gen_ok}
    if not gen_ok:
        print("[auto] ✗ 续写阶段失败，终止")
        # ★★ 2026-10-05：优先用本轮 gen.reason（ai_continue 现在保证失败时
        #   也会写 LAST_DECISION）；再加一道保险：若 reason 看起来像
        #   "N 字达标/已采纳"（那是**成功**的语气，不该出现在失败里），
        #   说明拿到的是别处的残留值 → 换成明确的失败描述。
        _gr = (result["gen"] or {}).get("reason") or ""
        if ("达标" in _gr) or ("已采纳" in _gr):
            _gr = "续写阶段失败（未产生本轮结果）"
        result["reason"] = _gr or "续写阶段失败"
        _cleanup_tail()          # ★ 失败更要清（弹窗多半正卡在异常态）
        return result

    # ================= 阶段二：衔接 =================
    print("\n" + "-" * 58)
    print("  【阶段二】衔接（关弹窗 → 等正文写入）")
    print("-" * 58)
    if close_dialog:
        close_continue_dialog(page)

    # ★ 效率改造（2026-10-04 实测）：原来是固定 `time.sleep(settle=2.0)`，
    #   每章白等 2 秒。而且紧随其后的 `wait_body_change()` 本来就在轮询
    #   「正文写入」，所以那 2 秒是**重复等待**。
    #   现在把 settle 改成**有上限的非阻塞等待**：正文一变就立刻继续，
    #   没变也最多等 settle 秒（上限与旧行为一致，所以只会更快、不会更差）。
    if settle and settle > 0:
        _sr = wait_until(
            lambda: get_body_text(page).strip() != "" and
            len(get_body_text(page)) != _raw_before,      # ★ 原始长度判据
            timeout=float(settle), interval=0.06, desc="等正文写入(settle)")
        if _sr.ok:
            print(f"[auto] ✓ 正文已写入（{_sr.elapsed:.2f}s，settle 提前结束）")
        else:
            print(f"[auto]   settle 用满 {settle:.1f}s，交给 wait_body_change 继续等")

    # 等正文真的变了（采纳生效）
    # ★ before_len 用**原始长度**（判据）、before_words 用**站点口径**（展示）
    new_len = wait_body_change(page, before_len=_raw_before,
                               before_words=body_before, timeout=25.0)
    result["body"] = new_len
    if new_len <= 0:
        print("[auto] ✗ 正文为空，无法审稿，终止")
        result["reason"] = "采纳后正文为空"
        _cleanup_tail()          # ★ 失败更要清（弹窗多半正卡在异常态）
        return result
    if body_before >= 0 and new_len == body_before:
        print(f"[auto] ⚠ 正文字数没变（{new_len}），可能采纳没生效，仍继续审稿")

    if not do_review:
        print("[auto] do_review=False，停在衔接完成")
        result["review"] = True
        # ★ do_review=False 时「续写+采纳」就是全部工作，故 ok 由续写决定
        result["ok"] = bool((result["gen"] or {}).get("ok", True))
        result["reason"] = "仅续写（未审稿）"
        _cleanup_tail()          # ★ 只续写时更要把续写弹窗清干净
        return result

    # ================= 阶段三：审稿 =================
    print("\n" + "-" * 58)
    print("  【阶段三】AI 审稿")
    print("-" * 58)

    # ★★ 审稿前校验章号（用户问「你续写完了，你知道是哪一章吗？」）
    #   审稿作用在「编辑器当前打开的章」。若中途站点自己跳了章
    #   （例：自动新建章节后会跳到新章），就会审错章。
    #   这里显式确认一次；不匹配就切回目标章，切不动才放弃。
    if chapter:
        want_no = -1
        m = re.search(r"第\s*(\d+)\s*章", chapter)
        if m:
            want_no = int(m.group(1))
        if want_no > 0:
            cur_no = current_chapter_no(page)
            if cur_no == want_no:
                print(f"[auto] ✓ 审稿前核对：当前正是第{want_no}章")
            elif cur_no < 0:
                print("[auto] ⚠ 读不出当前章号（无 active 标记）→ 继续")
            else:
                print(f"[auto] ⚠ 当前是第{cur_no}章，但目标是第{want_no}章"
                      f"（续写后站点跳章了？）→ 切回")
                open_chapter(page, which=chapter, wait=2.0)
                read_body_settled(page, timeout=8.0)
                back_no = current_chapter_no(page)
                if back_no == want_no:
                    print(f"[auto] ✓ 已切回第{want_no}章")
                else:
                    print(f"[auto] ✗ 切不回第{want_no}章（现为第{back_no}章）"
                          f"→ 终止，避免审错章")
                    result["reason"] = (f"审稿前章节错位：目标第{want_no}章，"
                                        f"实际第{back_no}章")
                    _cleanup_tail()      # ★ 失败更要清（弹窗多半正卡在异常态）
                    return result

    rev_ok = ai_review(
        page,
        model=review_model, model_card_name=review_card,
        model_card_hint=review_card_hint
        or MODEL_CARD_HINT.get(review_card, ""),
        associate=review_associate,
        requirement=review_req, req_tab=req_tab,
        instruction=review_instruction,
        start=True, wait_pane=review_wait,
        wait_done=True, done_timeout=review_done_timeout,
        replace=replace, select_all=select_all)
    result["review"] = rev_ok
    # ★ 统一返回契约：ok / reason 与 review / gen / body 并存。
    #   原实现没有 ok / reason，导致 `ai_batch_chapters` 读 `r.get("reason")`
    #   恒为 None、失败原因丢失；GUI 也只能靠 r.get("ok") 拿到 None。
    result["ok"] = bool(rev_ok)
    result["reason"] = ("审稿+替换完成" if rev_ok
                        else "审稿阶段未成功（详见 gen.reason 与截图）")

    # ★ 终局收尾：把审稿抽屉关掉，免得盖住正文区（影响后续读正文/下一章操作）
    if rev_ok and replace:
        try:
            close_review_pane(page)
        except Exception:
            pass

    # ★★ 终局收尾（2026-10-05 新增，用户实测日志定位）：
    #   一章结束后必须把**续写结果页/续写弹窗**也清干净，见 `_cleanup_tail`。
    #   （无论本章成功还是失败都要清，才能保证"下一章必报错"不再出现。）
    _cleanup_tail()

    print("\n" + "=" * 58)
    print("  ★ 一章自动流程结束")
    print(f"    续写结果 : {result['gen'].get('reason') if result['gen'] else '失败'}")
    print(f"    正文     : {body_before} → {result['body']} 字")
    print(f"    审稿替换 : {'✓ 完成' if rev_ok else '✗ 失败'}")
    print("=" * 58)
    return result

def ai_batch_chapters(page: Page,
                      start: int = 1,
                      end: int = 10,
                      plot: str = "",
                      plot_for: Optional[Callable[[int], str]] = None,
                      # ---- 续写参数（透传 ai_auto_chapter）----
                      gen_model: str = "细腻版",
                      gen_associate: str = "正常",
                      relate_count: int = 10,
                      shortcut: str = "",
                      min_words: int = 2100,
                      max_words: int = 2300,
                      max_retry: int = 5,
                      best_effort: bool = True,
                      gen_timeout: float = 300.0,
                      # ---- 审稿参数 ----
                      do_review: bool = True,
                      review_model: str = "智慧版",
                      review_card: str = "智慧版-6A",
                      review_card_hint: str = "",
                      review_associate: str = "正常",
                      review_req: str = "",
                      req_tab: str = "快捷选项",
                      review_instruction: str = "",
                      review_done_timeout: float = 600.0,
                      replace: bool = True,
                      select_all: bool = True,
                      # ---- 节奏控制 ----
                      chapter_delay: float = 3.0,
                      auto_new: bool = True,
                      stop_on_fail: bool = False,
                      # ---- ★ 进度回调 / 中止（2026-10-04 新增）----
                      on_progress: Optional[Callable[[dict], None]] = None,
                      should_stop: Optional[Callable[[], bool]] = None) -> dict:
    """★★ 批量跑章：第 start ~ end 章，逐章「一条龙」。

    每章流程：
      ① 确保左栏有「第N章」（缺则点「新建章节」自动补）
      ② 切到「第N章」
      ③ 生成该章 plot：plot_for(N)（指令模板自动渲染）或共用 plot
      ④ ai_auto_chapter（续写 → 采纳 → 审稿 → 替换）
      ⑤ 下一章

    Args:
        start / end:  章号范围（含两端）
        plot:         所有章共用的剧情文本（plot_for 为 None 时用）
        plot_for:     ★ 回调，给定章号返回该章 plot。
                      典型：lambda no: proj.render_template(current=no)
                      这样指令模板里的 #@ 会自动替换成当前章的细纲。
        ... 其余透传给 ai_auto_chapter（见其签名）
        chapter_delay: 每章之间额外静置（等站点稳定）
        stop_on_fail: 某章失败就停（默认 False：失败也继续跑下一章）
        on_progress:  ★ 逐章进度回调，每章**开始前**和**结束后**各调一次：
                      ``{"no": 3, "total": 8, "index": 1,
                         "phase": "start"|"done",
                         "ok": True, "words": 2210, "elapsed": 130.2,
                         "reason": "", "done_count": 1, "ok_count": 1}``
                      界面用它画进度条 / 算 ETA / 填结果表。
                      回调抛异常会被吞掉，不影响跑章。
        should_stop:  ★ 中止判据（无参、返回 bool）。默认用模块级的
                      `cancel_requested`（界面点「停止」会置位）。
                      返回 True 时在**章与章之间**停下，并把 `aborted=True`
                      放进返回值。章内的长等待由 `wait_generation` /
                      `wait_review_done` 的 `should_abort` 负责立刻退出。

    Returns:
        {"total": N, "ok": M, "failed": [...], "results": [{no, ok, ...}],
         "aborted": bool, "elapsed": 秒}
    """
    if end < start:
        print("[batch] ✗ 结束章号 < 起始章号")
        return {"total": 0, "ok": 0, "failed": [], "results": [],
                "aborted": False, "elapsed": 0.0}

    _should_stop = should_stop or cancel_requested
    _total = end - start + 1
    _t_all = time.time()

    def _emit(**kw) -> None:
        """安全地发一次进度（回调异常不影响跑章）。"""
        if on_progress is None:
            return
        try:
            on_progress(kw)
        except Exception as e:
            print(f"[batch] ⚠ 进度回调异常（忽略）：{e}")

    print("=" * 60)
    print(f"  ★★ 批量跑章：第 {start} ~ {end} 章（共 {_total} 章）")
    print(f"     模型={gen_model} 联想={gen_associate} 关联={relate_count}章")
    print(f"     采纳 {min_words}~{max_words} 字 · 最多重生成 {max_retry} 次"
          f" · 审稿={'是' if do_review else '否'}")
    print(f"     plot 来源={'指令模板自动渲染(#@=当前章)' if plot_for else ('固定('+str(len(plot))+'字)')}")
    print("=" * 60)

    results: List[dict] = []
    failed: List[int] = []
    aborted = False

    for no in range(start, end + 1):
        # ★★ 中止检查（章与章之间）：用户点「停止」后不要让下一章再开跑
        if _should_stop():
            print(f"[batch] ⏹ 收到停止请求，在第{no}章之前停下")
            aborted = True
            break

        index = no - start + 1
        t_ch = time.time()
        print("\n" + "#" * 60)
        print(f"#  第 {no}/{end} 章 开始（{index}/{_total}）")
        print("#" * 60)
        _emit(no=no, total=_total, index=index, phase="start",
              done_count=len(results),
              ok_count=sum(1 for x in results if x["ok"]),
              elapsed=time.time() - _t_all)

        # ① 确保章节存在（★ 逐章边建边跑；auto_new=False 时不新建）
        if auto_new:
            if not ensure_chapter(page, no):
                print(f"[batch] ✗ 第{no}章无法就位，跳过")
                failed.append(no)
                results.append({"no": no, "ok": False, "reason": "章节缺失",
                                "seconds": time.time() - t_ch})
                _emit(no=no, total=_total, index=index, phase="done",
                      ok=False, words=0, elapsed=time.time() - t_ch,
                      reason="章节缺失", done_count=len(results),
                      ok_count=sum(1 for x in results if x["ok"]))
                if stop_on_fail:
                    break
                continue
        elif no not in chapter_numbers(page):
            print(f"[batch] ✗ 第{no}章不存在且未开启自动新建，跳过")
            failed.append(no)
            results.append({"no": no, "ok": False,
                            "reason": "章节缺失(未开自动新建)",
                            "seconds": time.time() - t_ch})
            _emit(no=no, total=_total, index=index, phase="done",
                  ok=False, words=0, elapsed=time.time() - t_ch,
                  reason="章节缺失(未开自动新建)", done_count=len(results),
                  ok_count=sum(1 for x in results if x["ok"]))
            if stop_on_fail:
                break
            continue

        # ② 切到该章
        print(f"[batch] 切到第{no}章 …")
        open_chapter(page, which=f"第{no}章", wait=2.5)
        # ★★ 2026-10-05（用户要求「改在应用层」+ 指点思路）：
        #   原来是 `time.sleep(chapter_delay)`（默认 **每章固定睡 3 秒**）。
        #   用户指点：「你只要停留的时间够，点的按钮出来就行。」
        #   ⇒ 改成**等"下一步要用的东西"出现**（章节列表 / 续写按钮），
        #     再配一个短随机延迟打散机械节奏。
        #   `chapter_delay` 的语义 = **最长愿意等多久**（不再是固定睡眠）；
        #   最坏情况与旧行为一致，正常情况每章省下 ~2.5 秒。
        _cd = max(float(chapter_delay), 0.0)
        if _cd > 0:
            wait_until(lambda: _chapter_ready(page),
                       timeout=_cd, interval=0.05, desc="切章后可用（章间）")
        A.human_pause(0.2, 0.6)


        # ③ 生成 plot
        this_plot = plot_for(no) if plot_for else plot
        if not this_plot.strip():
            print(f"[batch] ⚠ 第{no}章 plot 为空（细纲没填/模板没渲染出来）"
                  f"—— 仍继续，看站点是否自带内容")

        # ④ 一条龙
        try:
            r = ai_auto_chapter(
                page,
                plot=this_plot, chapter=f"第{no}章",
                gen_model=gen_model, gen_associate=gen_associate,
                relate_count=relate_count, shortcut=shortcut,
                min_words=min_words, max_words=max_words,
                max_retry=max_retry, best_effort=best_effort,
                gen_timeout=gen_timeout,
                close_dialog=True, settle=2.0,
                do_review=do_review,
                review_model=review_model, review_card=review_card,
                review_card_hint=review_card_hint,
                review_associate=review_associate,
                review_req=review_req, req_tab=req_tab,
                review_instruction=review_instruction,
                review_done_timeout=review_done_timeout,
                replace=replace, select_all=select_all)
        except Exception as e:
            print(f"[batch] ✗ 第{no}章异常：{e}")
            r = {"ok": False, "reason": f"异常 {e}"}

        # ★ 统一走 ai_auto_chapter 的新契约：优先用 ok，回退到 review
        r = r if isinstance(r, dict) else {"ok": bool(r)}
        ok = bool(r.get("ok", r.get("review", False)))
        # ★ 失败原因现在真的能拿到了（原来 r.get("reason") 恒为 None）
        reason = r.get("reason") or ""
        # ★★ 2026-10-05 修正：只在**成功**时才允许回退到 gen.reason。
        #   失败时若回退到 gen.reason，会把上一章的「2028 字达标，已采纳」
        #   显示成本章失败原因（用户实测日志里就是这个误导）。
        if not reason and ok and r.get("gen"):
            reason = (r["gen"] or {}).get("reason") or ""
        # 失败但没拿到原因 → 给个明确的兜底，绝不显示"达标/已采纳"这种成功语气
        if not ok and not reason:
            _gr = ((r.get("gen") or {}).get("reason") or "")
            reason = (_gr if ("失败" in _gr or "打不开" in _gr or "点不到" in _gr
                              or "没有" in _gr or "超时" in _gr)
                      else "续写/审稿阶段未成功（详见运行日志）")
        secs = time.time() - t_ch
        # ★★ 区分「真的失败」和「被用户停止」：
        #   章内的长等待（等生成/等审稿）收到停止请求时会立刻退出并返回失败，
        #   但这不是章本身的问题 —— 不能算进失败列表，否则界面会把
        #   "被中止的那一章"报成失败，误导「从失败章重跑」。
        r_aborted = (not ok) and _should_stop()
        if r_aborted:
            reason = "已中止"
        results.append({"no": no, "ok": ok,
                        "body": r.get("body"),
                        "seconds": secs,
                        "reason": reason,
                        **({"aborted": True} if r_aborted else {})})
        _emit(no=no, total=_total, index=index, phase="done",
              ok=ok, aborted=r_aborted, words=r.get("body") or 0,
              elapsed=secs, reason=reason, done_count=len(results),
              ok_count=sum(1 for x in results if x["ok"]),
              total_elapsed=time.time() - _t_all)
        if ok:
            print(f"[batch] ✓ 第{no}章完成（{secs:.0f}s）")
        elif r_aborted:
            print(f"[batch] ⏹ 第{no}章因用户停止而中断（{secs:.0f}s）")
            aborted = True
            break
        else:
            print(f"[batch] ✗ 第{no}章失败（{secs:.0f}s）"
                  + (f"（{reason}）" if reason else ""))
            failed.append(no)
            if stop_on_fail:
                break

    ok_cnt = sum(1 for x in results if x["ok"])
    elapsed_all = time.time() - _t_all
    print("\n" + "=" * 60)
    if aborted:
        print(f"  ⏹ 批量跑章已中止：已完成 {ok_cnt}/{len(results)} 章"
              f"（目标 {_total} 章）")
    else:
        print(f"  ★ 批量跑章结束：{ok_cnt}/{len(results)} 章成功"
              f"{'（失败章：' + ','.join(map(str, failed)) + '）' if failed else ''}")
    for x in results:
        if not x["ok"]:
            print(f"    第{x['no']}章：{x['reason'] or '未记录原因'}")
    print("=" * 60)
    if not aborted:
        _shot(page, "batch_final")
    return {"total": len(results), "ok": ok_cnt,
            "failed": failed, "results": results,
            "aborted": aborted, "elapsed": elapsed_all}

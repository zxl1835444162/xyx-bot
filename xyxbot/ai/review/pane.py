"""审稿抽屉：打开 / 是否已开 / 关闭 / 框内是否当前章。

本文件由原巨型模块拆分而来（Phase C2/C1），拆分时按 AST 依赖做了拓扑排序，
每个模块只 import 排在自己前面的模块，不存在循环引用。
"""

from __future__ import annotations

from playwright.sync_api import Page
from xyxbot.ai.elements import CLICK_FAST_TIMEOUT, _fill_first, _safe_click, _shot, cancel_requested, dismiss_dialogs
from xyxbot.ai.selectors import AI_SELECTORS, ANCHOR_TEXT, REVIEW_CARD_ALT, REVIEW_CARD_SEL, REVIEW_PANE_SEL, REVIEW_SEP
from xyxbot.waiting import wait_gone, wait_until, wait_visible

from xyxbot.ai.review.text import _same_body, read_review_box, strip_review_wrapper

__all__ = ["_click_review_button", "_pane_body_is_current", "close_review_pane", "open_review_pane", "review_pane_open"]



def _pane_body_is_current(page: Page, expect_body: str) -> bool:
    """抽屉**已经开着**时：框里的正文是不是当前章。不是就关掉重开。

    ★★ 抽屉开着换章不会刷新 —— 用户报障 + 探针坐实。
    返回 True = 可以直接用（内容对得上，或调用方不要求校验）。
    返回 False = 已经关掉了旧抽屉，调用方应走"重开"流程。
    """
    if not expect_body:
        print("[ai] ✓ 审稿面板已在")
        return True
    cur = strip_review_wrapper(read_review_box(page))
    if _same_body(cur, expect_body):
        print(f"[ai] ✓ 审稿面板已在，且框内正文与当前章一致"
              f"（{len(cur)} 字）")
        return True
    # 内容对不上 → 关掉重开，强制站点重灌当前章正文
    print("[ai] ⚠ 审稿抽屉开着但框内正文不是当前章"
          f"（框内 {len(cur)} 字 / 当前章 {len(expect_body)} 字）"
          f"→ 关掉重开以刷新")
    try:
        close_review_pane(page, wait=1.0)
    except Exception:
        pass
    return False



def _click_review_button(page: Page, attempt: int) -> None:
    """② 点顶部「AI审稿」。

    ★ 短超时原生点击 + JS 降级（站点残留遮罩会拦原生点击，
      详见 CLICK_FAST_TIMEOUT 处说明）
    """
    try:
        btn = page.locator(AI_SELECTORS["btn_review"][0]).first
        if btn.count():
            try:
                btn.scroll_into_view_if_needed(timeout=CLICK_FAST_TIMEOUT)
            except Exception:
                pass
            try:
                btn.click(timeout=CLICK_FAST_TIMEOUT)
                print(f"[ai] ✓ 已点「AI审稿」（第 {attempt} 次）")
            except Exception:
                btn.evaluate("e => e.click()")
                print(f"[ai] ✓ 已点「AI审稿」（第 {attempt} 次，JS 降级）")
        else:
            print(f"[ai] ⚠ 第 {attempt} 次：找不到「AI审稿」按钮")
    except Exception as e:
        print(f"[ai] ⚠ 第 {attempt} 次点击失败：{str(e).splitlines()[0]}")



def open_review_pane(page: Page, wait: float = 0.6,
                     max_try: int = 4,
                     expect_body: str = "") -> bool:
    """点顶部「AI审稿」，等右侧抽屉面板出现。

    ★ 实测坑：跟续写一样，打开作品后常有干扰弹窗
      （「是否默认打开上次章节？」「国庆特惠」通知）挡住工具栏，
      导致点击超时或点了没反应。

    ★★ 面板已开时**要不要先关后开**（2026-10-05 用户报障坐实）：
      ★★★ 先前的"证伪"结论是**错的**，现按用户反馈纠正：

      用户原话：「审稿的时候，如果不刷新审稿，他是原来的内容」。

      真机探针 `_probe_refresh.py` 实测（**抽屉一直开着**，换章）：
        [A] 第1章，抽屉已开：框内 84 字（第1章）
        [B] 不关抽屉切第2章 → 等 0/0.5/1.5/3.0s：框内仍是 84 字（第1章）
        [C] 不关抽屉切第3章 → 框内仍是 84 字（第1章）
        [D] 关掉抽屉→重开 → 框内 123 字（第3章，正确刷新）
      ⇒ **抽屉不关就换章，站点不会重灌「待审文本」，一直是旧章内容。**

      我之前之所以误判成"不存在"，是因为复刻流程时**自己把抽屉关了**，
      而真实场景里抽屉**一直开着** —— 差异就在这一步。

      ⇒ 所以：面板已开时**必须校验框内是不是当前章正文**；不是就
        「关掉 → 重开」，强制站点重灌。校验靠 `expect_body`（当前编辑器正文）。

    Args:
        wait:        点击后等待秒数
        max_try:     最多尝试几次
        expect_body: ★ 期望框内应有的正文（一般是 `get_body_text(page)`）。
                     给了就校验；不符则关抽屉重开。留空则退化为旧行为。
    """
    print("[ai] --- 打开「AI审稿」面板 ---")

    # ★★ 面板已开：先看框里是不是**当前章**的正文
    #    （抽屉开着换章不会刷新 —— 用户报障 + 探针坐实）
    if review_pane_open(page):
        if _pane_body_is_current(page, expect_body):
            return True

    for attempt in range(1, max_try + 1):
        # ① 清干扰（有则关、没则跳过）
        try:
            n = dismiss_dialogs(page, verbose=(attempt == 1))
            if n and attempt > 1:
                print(f"[ai] 清掉了 {n} 个干扰弹窗")
        except Exception:
            pass

        if review_pane_open(page):
            print("[ai] ✓ 审稿面板已在")
            return True

        # ② 点「AI审稿」
        _click_review_button(page, attempt)

        # ③ 等面板
        #   ★ 效率改造（2026-10-04 实测）：原来是「固定 sleep(wait=0.6)
        #     + 最多 8 次 × sleep(0.5)」→ 最快 1.1 秒才返回、最坏 4.6 秒。
        #     现在是一次条件等待：面板一出现就继续。
        #   ★★ 谓词必须是 lambda：`review_pane_open` 需要 page 参数。
        #     写成 `wait_until(review_pane_open, ...)` 会每轮抛 TypeError
        #     被吞掉 → 必然超时 7.6 秒，再白重做一轮点击+清干扰
        #     （实测每章白等 8.5 秒；而面板其实 0.3 秒就出来了）。
        if wait_until(lambda: review_pane_open(page),
                      timeout=max(float(wait), 0.6) + 3.0,
                      interval=0.08, desc="审稿面板出现").ok:
            print("[ai] ✓ 审稿面板已出现")
            return True
        print("[ai]   面板未出现，重试…")

    print("[ai] ✗ 审稿面板打不开")
    _shot(page, "ai_review_pane_missing")
    return False




def review_pane_open(page: Page) -> bool:
    """审稿面板是否已打开（★ 用文字锚点，不依赖动态类名）。"""
    try:
        loc = page.locator(REVIEW_PANE_SEL)
        return bool(loc.count() and loc.first.is_visible())
    except Exception:
        return False




def close_review_pane(page: Page, wait: float = 1.0, max_try: int = 3) -> bool:
    """关闭右侧「AI审稿」抽屉。

    ★ 为什么要这个：一条龙终局时审稿抽屉是**开着的**，
      它盖住右半边，会导致后续读正文/点击图到错元素
      （2026-10-03 E2E 结论段读到 216 字就是这个原因）。

    策略（有则关、没则跳过，不抛异常）：
      ① 抽屉自己的关闭按钮 `button[aria-label='close']`
      ② `button[aria-label='close'].n-base-close.n-card-header__close`
      ③ ESC
      ④ 点遮罩 `.n-modal-mask` / 抽屉外部
    """
    if not review_pane_open(page):
        print("[ai] 审稿抽屉未开，无需关闭")
        return True
    print("[ai] --- 关闭审稿抽屉 ---")
    for _ in range(1, max_try + 1):
        # ① / ② 关闭按钮
        for sel in [
            ".n-card-header button[aria-label='close']",
            "button[aria-label='close'].n-card-header__close",
            ".n-card-header .n-base-close",
            ".n-drawer button[aria-label='close']",
            ".n-drawer .n-base-close",
            "button[aria-label='close']",
        ]:
            try:
                loc = page.locator(sel)
                n = loc.count()
                for i in range(min(n, 6)):
                    b = loc.nth(i)
                    try:
                        if not b.is_visible():
                            continue
                        _safe_click(b, label="关闭审稿抽屉")
                    except Exception:
                        continue
                    # ★ 条件等待抽屉关掉（原来固定 sleep(wait)=1.0s）
                    if wait_gone(lambda: review_pane_open(page),
                                 timeout=max(float(wait), 1.0),
                                 interval=0.05, desc="审稿抽屉关闭").ok:
                        print(f"[ai] ✓ 已关闭审稿抽屉（点 {sel}）")
                        return True
            except Exception:
                continue
        # ③ ESC
        try:
            page.keyboard.press("Escape")
            if wait_gone(lambda: review_pane_open(page),
                         timeout=max(float(wait), 1.0),
                         interval=0.05, desc="审稿抽屉关闭").ok:
                print("[ai] ✓ 已关闭审稿抽屉（ESC）")
                return True
        except Exception:
            pass
        # ④ 点遮罩 / 空白处
        try:
            for sel in [".n-modal-mask", ".n-drawer-mask", "body"]:
                m = page.locator(sel).first
                if m.count():
                    m.click(position={"x": 8, "y": 8},
                            timeout=CLICK_FAST_TIMEOUT)
                    if wait_gone(lambda: review_pane_open(page),
                                 timeout=max(float(wait), 1.0),
                                 interval=0.05, desc="审稿抽屉关闭").ok:
                        print(f"[ai] ✓ 已关闭审稿抽屉（点 {sel}）")
                        return True
        except Exception:
            pass
    print("[ai] ⚠ 审稿抽屉仍未关（继续，不阻断）")
    return not review_pane_open(page)

"""AI 审稿（面板、读稿、填写要求、等结果、替换正文）。

本文件由 `xyxbot/ai.py` 拆分而来（Phase C1）。拆分时按 AST 依赖做了拓扑排序，
所以每个模块只 import 排在自己前面的模块，不存在循环引用。
"""

from __future__ import annotations

from xyxbot.waiting import wait_gone, wait_until, wait_visible
from playwright.sync_api import Page
import time

from xyxbot.ai.body import get_body_text
from xyxbot.ai.current import _text_of, current_review_requirement
from xyxbot.ai.elements import CLICK_FAST_TIMEOUT, _fill_first, _safe_click, _shot, cancel_requested, dismiss_dialogs
from xyxbot.ai.selectors import AI_SELECTORS, ANCHOR_TEXT, REVIEW_CARD_ALT, REVIEW_CARD_SEL, REVIEW_PANE_SEL, REVIEW_SEP
from xyxbot.ai.shortcuts import pick_shortcut

__all__ = ["_same_body", "close_review_pane", "dismiss_review_confirm", "fill_review_text", "open_review_pane", "pick_review_requirement", "read_body_settled", "read_review_body", "read_review_box", "replace_review_result", "review_generating", "review_pane_open", "review_result_ready", "start_review", "strip_review_wrapper", "wait_review_done"]



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



def strip_review_wrapper(text: str) -> str:
    """★ 把「指令 + 分隔线 + 正文」剥回**纯正文**（2026-10-04 新增）。

    ★★ 为什么必须剥（用户问「是不是全部替换了框中的内容」→ 引出的真 bug）：
      我们的策略是「读出框里的正文 → 拼上指令 → 覆盖填回」。
      但 `read_review_box()` 读到的**不一定**是干净正文 —— 如果这个弹窗
      之前已经被我们处理过一次，框里就是 `指令 + 分隔线 + 正文`。
      再拼一次就会变成：

          指令B + 分隔线 + (指令A + 分隔线 + 正文)

      ⇒ **每跑一次就多包一层**，字数越审越多、内容重复。
      真机实测（探针 5）：
          827 → 867（1 层）→ 907（2 层）→ 946（3 层 + 换指令还残留旧指令）

      所以拼接前必须先剥：**取最后一条分隔线之后的全部内容**当正文。
      （用"最后一条"是因为正文本身不可能含这条分隔线，
        而多层套娃时最靠后的那条后面才是真正的正文。）

    Returns: 纯正文（无分隔线时原样返回，并 strip 掉首尾空白）
    """
    if not text:
        return ""
    if REVIEW_SEP not in text:
        return text.strip()
    # 取**最后**一条分隔线之后的内容
    body = text.rsplit(REVIEW_SEP, 1)[-1]
    return body.strip()



def _same_body(a: str, b: str, tol: float = 0.02) -> bool:
    """两份正文是否「基本是同一段」（用于校验抽屉里装的是不是当前章）。

    ★ 为什么不能直接 `==`：站点会做**换行归一化**
      （实测：待审框 827 字 vs 编辑器 854 字，同一章却差 27 字），
      所以用「长度接近 + 前缀/中段采样相似」来判断。

    判据（任一成立即算同一段）：
      · 一方为空 → False（空的不算"一致"）
      · 长度差异 ≤ max(12, tol·len) 且 前 60 字相同
      · 前 60 字相同 且 后 60 字相同（长度差异放宽到 10%）
    """
    a = (a or "").strip()
    b = (b or "").strip()
    if not a or not b:
        return False
    if a == b:
        return True
    la, lb = len(a), len(b)
    head_same = a[:60] == b[:60]
    tail_same = a[-60:] == b[-60:]
    tol_n = max(12, int(max(la, lb) * tol))
    if head_same and abs(la - lb) <= tol_n:
        return True
    if head_same and tail_same and abs(la - lb) <= max(la, lb) * 0.10:
        return True
    return False



def read_review_body(page: Page) -> str:
    """读「待审文本」框里的**纯正文**（自动剥掉可能存在的旧指令层）。

    这就是拼接时应该用的正文来源。
    """
    raw = read_review_box(page)
    return strip_review_wrapper(raw)



def read_review_box(page: Page) -> str:
    """读「待审文本」框里**已有的原始内容**（未做任何剥离）。

    ★★ 为什么这个比 `get_body_text` 更靠谱（2026-10-04 用户报障）：
      用户观察得很准：「这个审稿框，打开的时候，就有内容了」——
      站点**打开审稿面板时会自动把当前章正文填进「待审文本」框**。
      这才是**权威来源**：它就是站点自己认为"该审的文本"。

      而原实现是绕开这个框、去**编辑器**（`.tiptap.ProseMirror`）读正文，
      再拼上指令一起覆盖。问题在于：
        · 编辑器读的是**当前打开的那一章**，若章节切换有延迟，
          可能读到**上一章的正文** —— 这就是"有时候出差错"的根源
        · 编辑器可能还在重渲染 → 读到空

      改为**优先读这个框**：读到的就是站点要审的东西，天然不会串章。

    ★ 注意：本函数返回的是**原样内容**，可能含我们上次拼进去的指令层。
      拼接场景请用 `read_review_body()`（会自动剥）。

    Returns: 框内文本；读不到返回 ""
    """
    for s in AI_SELECTORS["review_text"]:
        try:
            loc = page.locator(s)
            if not loc.count():
                continue
            if not loc.first.is_visible():
                continue
            val = loc.first.input_value(timeout=400) or ""
            if val.strip():
                return val
        except Exception:
            continue
    return ""



def read_body_settled(page: Page, timeout: float = 6.0,
                      min_len: int = 1) -> str:
    """★ 等**待审文本框**里的正文就绪再读（2026-10-04 新增）。

    ★★ 为什么需要（用户报「审稿追加指令有时候出现差错」）：
      站点打开审稿面板时会**异步**把当前章正文填进「待审文本」框。
      如果面板刚开就立刻读，读到的是**上一次的残留值**或**空串**。
      这是"有时对、有时错"的典型特征 —— 取决于读取时机。

    ★ 与续写的差别（用户问「不跟续写一致吗」）：
      续写的 `fill_plot` 填的是**我们自己造的纯文本**，不依赖页面已有内容，
      所以没有时序问题；审稿必须**先读站点给的内容再拼接**，多一步"读"，
      就必然要有等待。

    ★★★ 返回值是**纯正文**（2026-10-04 二次修正：套娃 bug）：
      本函数**绝不能**把框里的原样内容直接返回给调用方去拼接 ——
      因为框里可能是我们上一轮拼好的 `指令 + 分隔线 + 正文`。
      真机实测（探针 5）：连续两轮审稿会变成
          827（原）→ 867（1 层）→ 907（2 层）→ 946（3 层）
      ⇒ 所以统一走 `strip_review_wrapper()` 剥掉旧指令层再返回。
      （判据用"最后一条分隔线之后"，多层时最靠后那条后面才是真正文。）

    策略：
      ① 优先等「待审文本框」出现**非空内容**（权威来源）
      ② 超时仍为空 → 退回等**编辑器**正文（兼容"站点没自动带入"的版本）
      ③ 都拿不到也返回最后一次结果，不阻塞流程，但留下明确日志
    """
    box = ""
    body = ""

    def _both_ok() -> bool:
        nonlocal box, body
        box = read_review_box(page)
        if len(box.strip()) >= min_len:
            return True
        body = get_body_text(page)
        return len(body.strip()) >= min_len

    res = wait_until(_both_ok, timeout=timeout, interval=0.12,
                     desc="待审文本就绪")

    if box.strip():
        # ★ 剥掉可能存在的旧指令层，只把纯正文交出去
        plain = strip_review_wrapper(box)
        if len(plain) != len(box.strip()):
            print(f"[ai] ⚠ 待审文本框里含旧指令层（原样 {len(box)} 字）"
                  f"→ 已剥出纯正文 {len(plain)} 字")
        if res.ok:
            print(f"[ai] ✓ 待审文本框已就绪（{len(plain)} 字正文，"
                  f"{res.elapsed:.2f}s）")
        else:
            print(f"[ai] ✓ 读到待审文本框（{len(plain)} 字正文，等待超时但已有内容）")
        return plain

    # 退化：框里没有，用编辑器正文
    if not body:
        body = get_body_text(page)
    if body.strip():
        print(f"[ai] ⚠ 待审文本框为空 → 退回用编辑器正文（{len(body)} 字）")
        return strip_review_wrapper(body)
    print(f"[ai] ⚠ 等了 {timeout:.1f}s，待审文本框与编辑器都为空"
          f"→ 追加指令将只填指令部分")
    return ""



def fill_review_text(page: Page, text: str = "",
                     instruction: str = "",
                     read_body: bool = True) -> bool:
    """填写「待审文本」。

    ★ 实测：打开面板时**已自动带入当前章正文**。

    ★★ 用户需求（2026-10-03）：待审文本是**自带章节正文的**，
      但希望在正文基础上**再追加一段指令**（类似「指令模板」的写法），
      比如：

          请按爽文节奏审改以下正文，重点检查毒点与逻辑断裂。
          ——以下为正文——
          （这里是章节原文…）

      所以设计成：
        - `instruction` 非空 → **正文 + 分隔 + 指令** 拼起来整段填进去
        - `text` 非空        → 直接用它（完全覆盖，不管正文）
        - 两个都空           → 沿用页面自带内容（不动）

    ★★★ 加固（2026-10-04，用户报「有时候出现差错」）：
      原实现有两处不够稳：
        ① `body = get_body_text(page)` —— **瞬时读，不等待**。
           编辑器重渲染的瞬间会读到空/半截/上一章正文。
           现在改为 `read_body_settled(page)`，最多等 6s 直到正文非空。
        ② `_settle()` 只取期望文本**尾部 40 字**去比对，且遍历所有匹配元素
           （任一命中即算过）—— 判据偏弱，容易"填炸了也算成功"。
           现在改为：**比对长度 + 前缀**，并要求**至少一个匹配元素**真的含
           我们填的开头（instruction/text 的开头比尾部更不容易撞车）。

    Args:
        text:        显式待审文本；给了就完全覆盖（优先级最高）
        instruction: ★ 指令模板/要求，会跟当前章正文拼在一起
        read_body:   instruction 模式下是否去读当前章正文来拼
                     （False = 只填指令）

    Returns:
        bool 是否成功
    """
    def _settle(expected: str, head: str, want_len: int) -> bool:
        """★ 等填进去的内容真的在 textarea 里（替代固定 sleep 0.8s）。

        判据（比原来强）：
          · 文本长度接近期望（±2% 或 ±5 字）—— 防"只得一半"
          · 且内容以我们填的**开头**为准（前缀匹配）—— 防填错框
        任一匹配元素满足即算落盘成功。超时不抛异常，只返回 False。
        """
        if want_len <= 0:
            return True
        tol = max(5, int(want_len * 0.02))

        def _ok() -> bool:
            for s in AI_SELECTORS["review_text"]:
                try:
                    loc = page.locator(s)
                    if not loc.count():
                        continue
                    cur = loc.first.input_value(timeout=200) or ""
                except Exception:
                    continue
                if head and head not in cur:
                    continue
                if abs(len(cur) - want_len) <= tol:
                    return True
            return False

        res = wait_until(_ok, timeout=3.0, interval=0.08, desc="待审文本落盘")
        if not res.ok:
            print("[ai] ⚠ 未能确认待审文本已完整落盘（内容长度/前缀对不上）")
        return res.ok

    # ① 显式 text → 直接覆盖
    if text:
        print(f"[ai] --- 填写待审文本（显式 {len(text)} 字）---")
        ok = _fill_first(page, AI_SELECTORS["review_text"], text,
                         label="待审文本")
        _settle(text, text.strip()[:20], len(text))
        return ok

    # ② 正文 + 指令 拼接
    #    ★★ 修正（2026-10-04）：读正文必须**等它渲染好**，不能瞬时读。
    #    ★★★ 二次修正（同日）：读到的是**纯正文**（read_body_settled 内部已剥
    #       旧指令层）。这里再做一次防御性剥离，确保任何来源都不会套娃。
    if instruction:
        body = read_body_settled(page) if read_body else ""
        body = strip_review_wrapper(body)      # ★ 防御性：即使上游漏剥也安全
        instr = instruction.strip()
        if body.strip():
            full = (f"{instr}\n\n"
                    f"{REVIEW_SEP}\n\n{body}")
            print(f"[ai] --- 待审文本 = 指令({len(instr)}字) "
                  f"+ 正文({len(body)}字) = {len(full)} 字 ---")
            head = instr[:20]          # 前缀取指令开头，稳定且不会撞车
        else:
            full = instr
            head = instr[:20]
            print(f"[ai] --- 待审文本 = 仅指令（{len(full)} 字，"
                  f"没读到正文）---")
        ok = _fill_first(page, AI_SELECTORS["review_text"], full,
                         label="待审文本")
        if ok:
            _settle(full, head, len(full))
        return ok

    # ③ 都空 → 不动（沿用页面自带当前章内容）
    print("[ai] 待审文本：留空，沿用页面自带内容")
    return True




def pick_review_requirement(page: Page, keyword: str = "",
                            tab: str = "快捷选项") -> bool:
    """选「审稿要求」里的提示词（★ 默认用「快捷选项」tab）。

    ★ 实测（2026-10-03）：
      ① 「审稿要求」下面有三个 tab：快捷选项 / 自定义 / 更多
         - 快捷选项：点开是**全屏提示词面板**（跟续写那边同一个 .prompt-row 列表）
         - 自定义：自己写一段要求
         - 更多：另一组预设
      ② 必须**先点 tab**，那一行下拉才会出现/切换。
      ③ ★ Naive UI 的样式怪癖：「快捷选项」和「更多」会**同时**带
         `--checked`，所以绝不能按 class 判断选中态，只能**按文字点**。

    Args:
        keyword: 提示词关键词（如「强盛集团云霄拯救过稿计划」）
        tab:     用哪个 tab，「快捷选项」/「自定义」/「更多」
    """
    print(f"[ai] --- 审稿要求：{tab} → {keyword or '(不改)'} ---")

    # ① 点 tab（★ 按文字点，不用 class：快捷选项/更多会同时带 --checked）
    #    ★ 实测：`{面板} .n-radio-button:has-text(...)` 常点击超时，
    #      因为 tab 在抽屉内但可能有遮挡/动画。改为 JS 精确定位 + 原生点击。
    tab_ok = False
    try:
        tab_ok = bool(page.evaluate("""(payload) => {
          const [anchor, label] = payload;
          const pane = [...document.querySelectorAll('.n-card-content')]
              .find(c => c.innerText.includes(anchor));
          if (!pane) return false;
          const t = [...pane.querySelectorAll('.n-radio-button')]
              .find(e => e.innerText.trim() === label);
          if (!t) return false;
          t.scrollIntoView({block: 'center'});
          t.click();
          return true;
        }""", [ANCHOR_TEXT, tab]))
        if tab_ok:
            print(f"[ai] ✓ 已切到「{tab}」tab（JS 点击）")
    except Exception as e:
        print(f"[ai] ⚠ JS 点 tab 失败：{str(e).splitlines()[0]}")

    if not tab_ok:
        # 降级：Playwright 短超时点击（+ JS/force 兜底，别白等 3 秒）
        try:
            tab_loc = page.locator(
                f"{REVIEW_PANE_SEL} .n-radio-button").filter(has_text=tab).first
            if tab_loc.count():
                if _safe_click(tab_loc, label=f"「{tab}」tab"):
                    print(f"[ai] ✓ 已切到「{tab}」tab（降级点击）")
            else:
                print(f"[ai] ⚠ 找不到「{tab}」tab，沿用当前")
        except Exception as e:
            print(f"[ai] ⚠ 点 tab 失败：{str(e).splitlines()[0]}，沿用当前")

    # ★ 效率改造：原来切 tab 后固定 sleep 0.5s。
    #   改成等**下拉行真的渲染出来**（tab 切换生效的可见信号）：
    #   2 个 .n-base-selection 都出现即可。找不到也无妨（下面有判空）。
    wait_until(lambda: page.locator(
        AI_SELECTORS["review_selects"][0]).count() >= 2,
        timeout=2.0, interval=0.05, desc="审稿要求行就绪")

    if not keyword:
        return True

    # ② 点那一行下拉（★ 第 2 个 .n-base-selection）
    try:
        sels = page.locator(AI_SELECTORS["review_selects"][0])
        if sels.count() < 2:
            print("[ai] ✗ 找不到「审稿要求」那一行下拉")
            _shot(page, "ai_review_req_row_missing")
            return False
        row = sels.nth(1)
        # 已经是目标了 → 跳过（回读断言，避免白点）
        cur = _text_of(row, timeout=400)
        if keyword and keyword in cur:
            print(f"[ai] 审稿要求已是「{cur[:40]}」，跳过")
            return True
        # ★ 短超时 + JS 降级（否则残留遮罩会让这里白等 4 秒，
        #   进而导致下面的面板等待/列表等待全部超时 —— 实测该步骤 29 秒）
        _safe_click(row, label="审稿要求下拉")
        print("[ai] ✓ 已打开审稿要求面板")
        # ★ 效率改造：原来固定 sleep 0.8s 等面板。改成等快捷选项面板出现。
        wait_visible(page, AI_SELECTORS["shortcut_panel"],
                     timeout=3.0, desc="审稿要求面板")
    except Exception as e:
        print(f"[ai] ✗ 点审稿要求失败：{str(e).splitlines()[0]}")
        _shot(page, "ai_review_req_open_fail")
        return False

    # ③ 用文字定位选提示词（复用续写的逻辑；★ verify_row=False → 内部回读
    #    「审稿要求」那一行，并在没对上时延迟重试一次）
    ok = pick_shortcut(page, keyword=keyword, panel_already_open=True,
                       verify_row=False)

    # ④ 回读断言（pick_shortcut 内部已等过，这里再确认一次最终态）
    after = current_review_requirement(page)
    if after and (keyword in after):
        print(f"[ai] ✓ 审稿要求已切换：{after[:50]}")
        return True
    print(f"[ai] ⚠ 审稿要求回读：「{after[:50]}」（目标含「{keyword}」）")
    return ok



def start_review(page: Page, wait: float = 0.5) -> bool:
    """点审稿卡片**底部固定栏**的「生成」按钮，开始审稿。

    ★ 踩坑（2026-10-03）：
      ① 全局 `button:has-text('生成')` → 命中左栏章节菜单浮层的
         「一键生成概要」，点错。
      ② 锁 `REVIEW_PANE_SEL`（.n-card-content）→ 找不到，因为
         **「生成」在 `.n-card__footer`，不在 `.n-card-content` 里**。
      正解：用 `REVIEW_CARD_SEL`（整个卡片），footer 就在其中。
    """
    print("[ai] --- 点「生成」（开始审稿）---")
    ok = False

    # ① 常规点击（卡片范围内，优先 footer）
    for sel in AI_SELECTORS["btn_review_start"]:
        try:
            loc = page.locator(sel)
            n = loc.count()
            if n:
                # ★ 短超时原生点击 + JS 降级（残留遮罩会拦原生点击，
                #   否则这里要白等满 5 秒；详见 CLICK_FAST_TIMEOUT 说明）
                try:
                    loc.last.click(timeout=CLICK_FAST_TIMEOUT)
                except Exception:
                    loc.last.evaluate("e => e.click()")
                ok = True
                print(f"[ai] ✓ 点击「生成」（{sel[:48]}…）")
                break
        except Exception as e:
            print(f"[ai] ⚠ 常规点击失败：{str(e).splitlines()[0]}")
            continue

    # ② JS 降级：沿「待审文本」卡片往上找到含「生成」的 footer 直接点
    if not ok:
        try:
            ok = bool(page.evaluate("""(anchor) => {
              const content = [...document.querySelectorAll('.n-card-content')]
                  .find(c => c.innerText.includes(anchor));
              if (!content) return false;
              const card = content.closest('.n-card');
              if (!card) return false;
              const btns = [...card.querySelectorAll('button')]
                  .filter(b => b.innerText.trim() === '生成');
              if (!btns.length) return false;
              btns[btns.length - 1].click();
              return true;
            }""", ANCHOR_TEXT))
            if ok:
                print("[ai] ✓ JS 降级点击（卡片 footer 内的生成）")
        except Exception as e2:
            print(f"[ai] ✗ JS 降级也失败：{str(e2).splitlines()[0]}")

    if not ok:
        _shot(page, "ai_review_start_failed")
        return False

    # ★ 效率改造（2026-10-04 实测）：原来是「点完固定 sleep(wait=0.5)」。
    #   改成条件等待「审稿真的开始」（出现生成中状态）；超时 =
    #   max(wait,0.5)+2.0（比原来更宽容），所以最坏情况不比旧实现差。
    #   ★ 这个等待**不参与成败判定**：ok 已由点击结果决定。
    started = wait_until(lambda: review_generating(page),
                         timeout=max(float(wait), 0.5) + 2.0,
                         interval=0.06, desc="审稿已开始")
    if started.ok:
        print(f"[ai] ✓ 已触发生成（{started.elapsed:.2f}s）")
    else:
        print("[ai] ✓ 已触发生成（未观测到生成中状态，继续）")
    return True



def review_generating(page: Page) -> bool:
    """审稿是否仍在生成中。

    ★ 判据（实测）：
        - 底部出现「停止生成」/ loading 按钮 → 生成中
        - 结果区出现「替换 / 插入」→ 已完成
        - 「深度思考中」toast 也在 → 生成中
    """
    try:
        # ① 结果区已经出现 → 肯定不是「生成中」
        if review_result_ready(page):
            return False
        # ② 「停止生成」按钮
        if page.locator("button:has-text('停止生成')").count():
            return True
        # ③ loading 型按钮
        if page.locator("button.n-button--loading").count():
            return True
        # ④ 「思考中」文案
        return bool(page.locator("text=思考中").count())
    except Exception:
        return False



def review_result_ready(page: Page) -> bool:
    """审稿结果是否已就绪（★ 权威判据：「替换 / 插入」按钮出现）。

    ★ 实测（2026-10-03 真机）：
        生成中 → 抽屉底部只有「生成」（disabled），**没有** success 型按钮
        完成后 → footer 出现一排：
                 【重新生成】【复制】【对比】【导出至作品】
                 **【替换 / 插入】**（n-button--success-type）
      所以「替换 / 插入」按钮出现 = 审稿完成，可以落盘。

    ★★ 踩坑（务必记住）：**不要用「全页文字含『替换』」做判据！**
      页面上别处（通知、其他卡片、隐藏元素）也可能带这俩字，
      会导致刚点完生成就误判「已完成（耗时 0s）」。
      必须**限定在审稿卡片的 footer 内 + 限定 success 型 class**。
    """
    try:
        # ★ 唯一硬判据：审稿卡片 footer 里的 success 型按钮
        for card_sel in (REVIEW_CARD_SEL, REVIEW_CARD_ALT):
            try:
                loc = page.locator(
                    f"{card_sel} .n-card__footer "
                    f"button.n-button--success-type")
                if loc.count() and loc.first.is_visible():
                    return True
            except Exception:
                continue
            try:
                loc = page.locator(f"{card_sel} button.n-button--success-type")
                if loc.count() and loc.first.is_visible():
                    return True
            except Exception:
                continue
        # 兜底：JS 里同样**限定在卡片 footer + success class**
        return bool(page.evaluate("""() => {
          const cards = document.querySelectorAll(
              '.chapter-right-workspace .n-card.chapter-side-pane-c, '
              + '.n-card.chapter-side-pane-card');
          for (const c of cards) {
            const footer = c.querySelector('.n-card__footer');
            if (!footer) continue;
            const ok = [...footer.querySelectorAll(
                'button.n-button--success-type')]
                .some(b => b.offsetParent !== null);
            if (ok) return true;
          }
          return false;
        }"""))
    except Exception:
        return False



def wait_review_done(page: Page, timeout: float = 600.0,
                     poll: float = 0.4,
                     confirm_hits: int = 2,
                     confirm_gap: float = 0.15) -> bool:
    """等审稿生成完成（等「替换 / 插入」按钮出现）。

    ★ 用户要求：审稿要跑几分钟很正常，所以要**耐心等满 timeout**，
      不要因为「字数稳定」之类的弱判据提前跳出。
      判据只有一条硬的：结果按钮栏出现。

    ★ 效率改造（本轮）：原来 `poll=1.5` 且「连续 2 次命中」——两次命中之间
      要等 1.5 秒，也就是**判定完成本身就固定慢 1.5 秒**；再加上粗轮询的
      期望延迟，每章在这个环节白等约 2 秒以上。

      现在拆开两个参数：
        * `poll=0.4`      —— 未完成时的轮询间隔（问得勤，但只是廉价查询）；
        * `confirm_gap=0.15` —— **两次确认命中之间的间隔**（防瞬时误判用，
          不需要 1.5 秒那么久；动画残影在 150ms 内就能分辨）。

    Args:
        timeout:      最长等多久（默认 600s = 10 分钟）
        poll:         轮询间隔
        confirm_hits: 连续命中几次才算完成（默认 2，防瞬时误判）
        confirm_gap:  两次确认之间的间隔（秒）

    Returns:
        bool 是否等到完成
    """
    print(f"[ai] --- 等审稿完成（最多 {timeout:.0f}s）---")
    t0 = time.time()
    last_beat = [0.0]
    # ★ "连续 confirm_hits 次命中"的状态机。
    #   把它写成**谓词内部状态**，就能复用 `wait_until` —— 从而白拿
    #   中止支持（用户点停止时不必等满 600 秒）与统一的心跳/超时语义。
    #   两次命中之间仍要求间隔 ≥ confirm_gap（防动画残影误判）。
    st = {"hits": 0, "last": 0.0}

    def _ready() -> bool:
        now = time.time()
        if review_result_ready(page):
            if st["hits"] == 0 or (now - st["last"]) >= confirm_gap:
                st["hits"] += 1
                st["last"] = now
            return st["hits"] >= confirm_hits
        st["hits"] = 0
        return False

    def _tick(_n):
        el = time.time() - t0
        if el - last_beat[0] >= 30:      # 每 ~30s 打一次心跳
            last_beat[0] = el
            print(f"[ai]   审稿生成中 … {el:.0f}s")

    res = wait_until(_ready, timeout=timeout, interval=poll,
                     on_poll=_tick, desc="审稿完成",
                     should_abort=cancel_requested)
    if res.aborted:
        print("[ai] ⏹ 审稿等待被中止（用户停止）")
        return False
    if res.ok:
        print(f"[ai] ✓ 审稿已完成（耗时 {res.elapsed:.0f}s）")
        return True
    print(f"[ai] ✗ 等审稿超时（{timeout:.0f}s）")
    _shot(page, "ai_review_timeout")
    return False



def replace_review_result(page: Page, wait: float = 1.0) -> bool:
    """点「替换 / 插入」，把审稿结果**落到正文**。

    ★ 这是审稿流程的**最后一步**（用户明确要求）：
        生成完 → 结果区出现【替换 / 插入】→ 点它 → 结果替换进正文。
    ★ 实测 DOM（2026-10-03）：
        button 文字 = "替换 / 插入"
        class      = n-button n-button--success-type n-button--small-type
        位置        = .n-card__footer（审稿抽屉底部）
    ★ 关弹窗原则：若出现二次确认框，**有则点确认、没有就跳过**，绝不阻塞。

    Returns:
        bool 是否点到「替换 / 插入」
    """
    print("[ai] --- 点「替换 / 插入」（落盘到正文）---")

    # ① 点击：优先用「类名 + 位置」精确点（比文字更稳）
    clicked = False
    for sel in AI_SELECTORS["btn_review_replace"]:
        try:
            loc = page.locator(sel)
            n = loc.count()
            if not n:
                continue
            btn = loc.last
            # ★ 不先 scroll_into_view_if_needed（它可能 15s 超时直接失败），
            #   直接 click；短超时失败后依次 JS / force 降级
            #   （残留遮罩会拦原生点击，长超时只会白等，详见 CLICK_FAST_TIMEOUT）
            try:
                btn.click(timeout=CLICK_FAST_TIMEOUT)
            except Exception:
                try:
                    btn.evaluate("e => e.click()")
                except Exception:
                    btn.click(timeout=CLICK_FAST_TIMEOUT, force=True)
            clicked = True
            print(f"[ai] ✓ 点击「替换 / 插入」（{sel[:52]}…）")
            break
        except Exception as e:
            print(f"[ai] ⚠ 常规点击失败：{str(e).splitlines()[0]}")
            continue

    # ② JS 降级：按类名找 success 型按钮直接 click()
    if not clicked:
        try:
            clicked = bool(page.evaluate("""() => {
              // 优先 footer 里的 success 型
              const cards = document.querySelectorAll(
                  '.chapter-right-workspace .n-card.chapter-side-pane-c, '
                  + '.n-card.chapter-side-pane-card');
              for (const c of cards) {
                const footer = c.querySelector('.n-card__footer') || c;
                const b = [...footer.querySelectorAll(
                    'button.n-button--success-type')]
                    .filter(x => x.offsetParent !== null);
                if (b.length) {
                  b[b.length - 1].scrollIntoView({block:'center'});
                  b[b.length - 1].click();
                  return true;
                }
              }
              // 兜底：文字匹配（去空格）
              const all = [...document.querySelectorAll('button')]
                .filter(b => b.offsetParent !== null
                    && (b.innerText||'').replace(/\\s/g,'').includes('替换'));
              if (all.length) { all[all.length-1].click(); return true; }
              return false;
            }"""))
            if clicked:
                print("[ai] ✓ JS 降级点击「替换 / 插入」")
        except Exception as e:
            print(f"[ai] ⚠ JS 降级失败：{str(e).splitlines()[0]}")

    if not clicked:
        print("[ai] ✗ 找不到「替换 / 插入」按钮")
        _shot(page, "ai_review_replace_failed")
        return False

    # ★ 效率改造：原来是固定 `sleep(wait=1.2)` 等替换落盘。
    #   替换是前端本地操作，通常几十毫秒就完成；这里改为**等正文真的变了**
    #   （与替换前对比字数/内容），一变就继续，最慢不超过 wait。
    try:
        body_before = get_body_text(page)
        wait_until(lambda: get_body_text(page) != body_before,
                   timeout=max(wait, 1.0), interval=0.08, desc="替换落盘")
    except Exception:
        time.sleep(min(wait, 0.5))      # 读不到正文时保守等一点

    # ③ 可能的二次确认框（有则点、没则跳过，绝不阻塞）
    try:
        n = dismiss_review_confirm(page)
        if n:
            print(f"[ai] 处理了 {n} 个替换确认框")
            # 确认框消失即可继续（原来固定 sleep 1.2s）
            wait_gone(lambda: any(
                page.locator(s).first.is_visible(timeout=60)
                for s in AI_SELECTORS["review_replace_confirm"]
                if page.locator(s).count()),
                timeout=2.0, desc="确认框关闭")
    except Exception:
        pass

    return True



def dismiss_review_confirm(page: Page, verbose: bool = True) -> int:
    """关掉「替换」可能弹出的二次确认框。

    ★ 原则（用户要求）：**有则关、没有就跳过**，绝不影响进程。
      返回点掉的个数（0 = 本来就没有）。
    """
    closed = 0
    for sel in AI_SELECTORS["review_replace_confirm"]:
        try:
            loc = page.locator(sel).first
            if loc.count() and loc.is_visible():
                _safe_click(loc, label="替换确认框")
                closed += 1
                if verbose:
                    print(f"[ai]   ✓ 点确认：{sel[:44]}")
                break
        except Exception:
            continue
    return closed

"""待审文本：剥离包装层 / 判同 / 读框 / 等就绪 / 填写落盘校验。

本文件由原巨型模块拆分而来（Phase C2/C1），拆分时按 AST 依赖做了拓扑排序，
每个模块只 import 排在自己前面的模块，不存在循环引用。
"""

from __future__ import annotations

from playwright.sync_api import Page
from xyxbot.ai.body import get_body_text
from xyxbot.ai.elements import CLICK_FAST_TIMEOUT, _fill_first, _safe_click, _shot, cancel_requested, dismiss_dialogs
from xyxbot.ai.selectors import AI_SELECTORS, ANCHOR_TEXT, REVIEW_CARD_ALT, REVIEW_CARD_SEL, REVIEW_PANE_SEL, REVIEW_SEP
from xyxbot.waiting import wait_gone, wait_until, wait_visible

__all__ = ["_compose_review_input", "_same_body", "_wait_review_text_settled", "fill_review_text", "read_body_settled", "read_review_body", "read_review_box", "strip_review_wrapper"]



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




def _wait_review_text_settled(page: Page, want_len: int, head: str) -> bool:
    """★ 等填进去的内容真的在 textarea 里（替代固定 sleep 0.8s）。

    判据（比原来强）：
      · 文本长度接近期望（±2% 或 ±5 字）—— 防"只得一半"
      · 且内容以我们填的**开头**为准（前缀匹配）—— 防填错框
    任一匹配元素满足即算落盘成功。超时不抛异常，只返回 False。

    ★★★ 加固（2026-10-04，用户报「有时候出现差错」）：原判据只看期望文本
      **尾部 40 字**、且遍历所有匹配元素（任一命中即算过）—— 偏弱，
      容易"填炸了也算成功"。现在改为**长度 + 前缀**，并要求真的含我们填的
      开头（开头比尾部更不容易撞车）。
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



def _compose_review_input(page: Page, instruction: str,
                          read_body: bool) -> tuple:
    """② 把「指令 + 分隔线 + 当前章正文」拼成待审文本。返回 (full, head)。

    ★★ 修正（2026-10-04）：读正文必须**等它渲染好**，不能瞬时读。
    ★★★ 二次修正（同日）：读到的是**纯正文**（read_body_settled 内部已剥
       旧指令层）。这里再做一次防御性剥离，确保任何来源都不会套娃。
    """
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
    return full, head



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
    # ① 显式 text → 直接覆盖
    if text:
        print(f"[ai] --- 填写待审文本（显式 {len(text)} 字）---")
        ok = _fill_first(page, AI_SELECTORS["review_text"], text,
                         label="待审文本")
        _wait_review_text_settled(page, len(text), text.strip()[:20])
        return ok

    # ② 正文 + 指令 拼接
    if instruction:
        full, head = _compose_review_input(page, instruction, read_body)
        ok = _fill_first(page, AI_SELECTORS["review_text"], full,
                         label="待审文本")
        if ok:
            _wait_review_text_settled(page, len(full), head)
        return ok

    # ③ 都空 → 不动（沿用页面自带当前章内容）
    print("[ai] 待审文本：留空，沿用页面自带内容")
    return True

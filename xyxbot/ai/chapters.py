"""章节导航（列表、打开、确认）。

本文件由 `xyxbot/ai.py` 拆分而来（Phase C1）。拆分时按 AST 依赖做了拓扑排序，
所以每个模块只 import 排在自己前面的模块，不存在循环引用。
"""

from __future__ import annotations

from xyxbot.waiting import wait_gone, wait_until, wait_visible
from playwright.sync_api import Page
from typing import Callable, List, Optional
import re
import time

from xyxbot.ai.body import chapter_word_count, get_body_text
from xyxbot.ai.current import _text_of
from xyxbot.ai.elements import CLICK_FAST_TIMEOUT, _safe_click, _shot, dismiss_dialogs
from xyxbot.ai.selectors import AI_SELECTORS

__all__ = ["_chapter_ready", "chapter_items", "chapter_numbers", "current_chapter_no", "ensure_chapter", "open_chapter"]



def chapter_items(page: Page):
    """定位左栏章节项（★ 用**容器** `.chapter-item`，不是标题 h3）。

    实测（2026-10-03）左栏 DOM：
        <div class="chapter-item chapter-item--active ...">
          <h3 class="chapter-item__title">第2章</h3>
          <span class="chapter-item__meta">104 字</span>
          ...
          <div class="chapter-item__hover-actions ...">… 生成</div>
        </div>
    ★ 坑1：`h3.chapter-item__title` 也能点，但**容器**更稳（标题很窄，36px）。
    ★ 坑2：容器里有个「生成」按钮，直接点容器别去点那个按钮。
    ★ 坑3：`chapter-item--active` 表示已打开。已打开的章节点它没用，
           要确认编辑器里真有内容（见 `editor_ready`）。
    """
    for sel in AI_SELECTORS["chapter_item"]:
        try:
            loc = page.locator(sel)
            if loc.count():
                return loc
        except Exception:
            continue
    return page.locator(".chapter-item")



def open_chapter(page: Page, which: str = "", index: int = 0,
                 wait: float = 2.5) -> bool:
    """打开章节列表里的某一章（★ 审稿前必须做，否则正文是空的）。

    Args:
        which: 章节标题关键词（如「第2章」）；留空则按 index 选
        index: which 为空时选第几个章节项（从 0 开始）
        wait:  点完之后等多久（等正文渲染）

    ★ 为什么要这步：进作品编辑器后**可能不会自动打开任何章节**。
      实测：`editor_ready()` 会因为 `.tiptap.ProseMirror` 存在而返回 True，
      但里面**一个字都没有**（正文区是空壳），需要真的点开一章。

    ★★ 踩坑（2026-10-03 实测）：
       1) 必须先 `dismiss_dialogs()`——「是否默认打开上次章节？」是居中模态，
          **会截获所有点击**，导致 `Locator.click: Timeout 4000ms exceeded`。
       2) 点**容器** `.chapter-item`，不要点 h3 标题（标题只有 36px 宽）。
       3) 点完要校验正文**非空**，光看 `editor_ready` 不算数。
    """
    # ⓪ ★ 先清弹窗（否则点击被拦截）
    dismiss_dialogs(page, verbose=False)

    body_now = get_body_text(page)
    if body_now and not which:
        print(f"[ai] 正文已有内容（{len(body_now)} 字），跳过打开章节")
        return True

    print(f"[ai] --- 打开章节（{which or f'第{index}个'}）---")
    items = chapter_items(page)
    n = items.count()
    if not n:
        print("[ai] ✗ 左栏没有章节项")
        _shot(page, "ai_open_chapter_failed")
        return False
    print(f"[ai]   左栏共 {n} 个章节")

    if which:
        target_i = None
        for i in range(n):
            try:
                t = _text_of(items.nth(i), timeout=400)
            except Exception:
                t = ""
            if which in t:
                target_i = i
                break
        if target_i is None:
            # ★ 根因修复（2026-10-03）：之前退回「第 index 个」（倒序列表第0个=最新章），
            #   会把内容写进错误的章节。现在退回「第1章（最小章号）」，并醒目警告。
            nos = chapter_numbers(page)
            first_no = min(nos) if nos else 1
            print(f"[ai] ⚠ 没找到含「{which}」的章节！退回第{first_no}章"
                  f"（而不是最新章，避免写错章节）")
            # 找到最小章号对应的下标
            target_i = 0
            for i in range(n):
                try:
                    t = _text_of(items.nth(i), timeout=400)
                except Exception:
                    t = ""
                if f"第{first_no}章" in t:
                    target_i = i
                    break
    else:
        target_i = min(index, n - 1)

    el = items.nth(target_i)
    # ★ 记下点击前的正文，用来判断"真的换章了"
    body_before = get_body_text(page)
    try:
        el.click(timeout=CLICK_FAST_TIMEOUT)
    except Exception as e:
        print(f"[ai] ⚠ 常规点击失败（{str(e).splitlines()[0]}），试 JS 点击")
        try:
            el.evaluate("e => e.click()")
        except Exception as e2:
            print(f"[ai] ✗ JS 点击也失败：{str(e2).splitlines()[0]}")
            _shot(page, "ai_open_chapter_failed")
            return False

    # 等正文渲染出来。
    # ★ 效率+正确性改造（2026-10-04 实测）：
    #   原实现是「先固定 sleep 0.7s，再看正文非空」——
    #     · 白等：正文通常 ~100ms 就渲染好了，那 0.7 秒纯属浪费（每章都吃）
    #     · 而且**判据不够严**：切章瞬间编辑器里还留着**上一章**的正文，
    #       "非空"会立刻成立 → 可能读到旧章内容（静默错章）。
    #   现在：轮询"正文非空 **且** 与点击前不同"，既快又更可靠。
    #     （点击前本来就是空章时，只要非空即算成功。）
    def _switched() -> bool:
        t = get_body_text(page)
        if not t.strip():
            return False
        return (not body_before.strip()) or (t != body_before)

    res = wait_until(_switched, timeout=max(wait, 2.0) * 2,
                     interval=0.08, desc="章节正文渲染")
    if res.ok:
        print(f"[ai] ✓ 已打开章节（正文 {chapter_word_count(page)} 字，"
              f"{res.elapsed:.2f}s）")
        return True
    print("[ai] ⚠ 点了章节但正文还是空的（可能是空章）")
    _shot(page, "ai_open_chapter_empty")
    return False



# ================================================================ 批量跑章 ★

def chapter_numbers(page: Page) -> List[int]:
    """只读：列出左栏所有章节的章号（按 DOM 顺序，站点是倒序）。

    章号从标题「第N章」里抠出来。失败/不识别返回 -1。
    """
    nos: List[int] = []
    try:
        items = page.locator(".chapter-item")
        n = items.count()
        for i in range(n):
            try:
                t = _text_of(items.nth(i), timeout=400)
            except Exception:
                t = ""
            m = re.search(r"第\s*(\d+)\s*章", t)
            nos.append(int(m.group(1)) if m else -1)
    except Exception:
        pass
    return nos



def current_chapter_no(page: Page) -> int:
    """只读：当前**已打开**（active）的章号；识别不了返回 -1。

    ★ 为什么要这个（用户问「你续写完了，你知道是哪一章吗？」）：
      一条龙流程里，续写和审稿都作用在「编辑器当前打开的那一章」。
      若中途站点自己跳了章（自动新建后会跳到新章），审稿就会**审错章**。
      有了这个函数就能在审稿前**校验**一次，把"审错章"变成可见的失败。

    判据：左栏 `.chapter-item--active`（实测站点用它标已打开的章）。
      兜底：若没有 active 项，退化为「编辑器正文能匹配到的那个章」——不做，
            直接返回 -1（宁可报未知，也不要猜错）。
    """
    try:
        act = page.locator(".chapter-item--active")
        n = act.count()
        for i in range(min(n, 8)):
            try:
                t = _text_of(act.nth(i), timeout=300)
            except Exception:
                t = ""
            m = re.search(r"第\s*(\d+)\s*章", t or "")
            if m:
                return int(m.group(1))
    except Exception:
        pass
    return -1



def ensure_chapter(page: Page, no: int, wait: float = 2.0,
                   max_new: int = 120) -> bool:
    """确保左栏存在「第 no 章」，缺就点「新建章节」自动补。

    ★ 实测（2026-10-03）：
      - 「新建章节」按钮 = `button:has-text('新建章节')`（左栏顶部，80x30）
      - 点一下会**立即**创建「第(当前最大+1)章」，标题自动递增、无需输入
        （会出现一个标题输入框，但已预填好标题，可忽略，按 Esc 失焦即可）
      - 章节列表是倒序（新章在最上、active）

    所以「按顺序补建」= 连续点 (no - 当前最大) 次即可。
    注意：只支持「往上补」（no > 当前最大）。若 no 已存在直接 True；
    若 no < 当前最大但不存在（比如删过导致跳号），无法靠新建补，返回 False。

    Args:
        no:      目标章号
        wait:    每次点完「新建章节」后的等待（秒）
        max_new: 最多新建几章（安全阀，防死循环）
    """
    nos = chapter_numbers(page)
    if no in nos:
        return True
    cur_max = max(nos) if nos else 0
    if no < cur_max:
        print(f"[ai] ✗ 第{no}章不存在且小于当前最大章号{cur_max}"
              f"（跳号，无法自动新建，需手动建/恢复）")
        return False
    need = no - cur_max
    if need > max_new:
        print(f"[ai] ✗ 要新建 {need} 章，超过安全上限 {max_new}")
        return False

    print(f"[ai] 缺第{no}章，连续新建 {need} 章（第{cur_max+1}~{no}章）…")
    for _ in range(need):
        if no in chapter_numbers(page):
            return True
        # 点「新建章节」
        clicked = False
        for attempt in range(3):
            try:
                btn = page.locator("button:has-text('新建章节')").first
                if _safe_click(btn, label="新建章节"):
                    clicked = True
                break
            except Exception:
                # 可能被标题输入框挡住 → 先 Esc 失焦再试
                try:
                    page.keyboard.press("Escape")
                except Exception:
                    pass
                time.sleep(0.6)
        if not clicked:
            print("[ai] ✗ 点「新建章节」失败")
            return False
        time.sleep(wait)
        # 点完可能聚焦标题输入框，Esc 失焦（不破坏已建章节）
        try:
            page.keyboard.press("Escape")
        except Exception:
            pass

    ok = no in chapter_numbers(page)
    if ok:
        print(f"[ai] ✓ 已新建到第{no}章")
    else:
        print(f"[ai] ✗ 新建后仍没有第{no}章（现有 {chapter_numbers(page)}）")
        _shot(page, "ai_ensure_chapter_failed")
    return ok



def _chapter_ready(page: Page) -> bool:
    """★ 章间「可以继续下一章」的判据（2026-10-05 新增）。

    ★ 用户指点：「你只要停留的时间够，点的按钮出来就行。」
      —— 不要判断"站点稳没稳"，而是判断**下一步要用的东西在不在**。

    下一章要用的东西是：
      · 左栏的章节列表项（`.chapter-item`）—— 切章要用
      · 或者「AI续写正文」按钮 —— 一条龙的入口
    任一可见即认为可以继续。
    任何异常都当作"未就绪"（继续等），绝不让本判据抛错影响主流程。
    """
    for sel in (AI_SELECTORS.get("chapter_item") or [".chapter-item"]):
        try:
            loc = page.locator(sel)
            if loc.count() > 0:
                return True
        except Exception:
            continue
    for sel in AI_SELECTORS["btn_continue"]:
        try:
            loc = page.locator(sel)
            if loc.count() > 0:
                return True
        except Exception:
            continue
    return False

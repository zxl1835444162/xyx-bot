"""打开一个已有作品（点卡降级 / 遮罩重试 / URL 校验 / 编辑器就绪）。

本文件由原巨型模块拆分而来（Phase C2/C1），拆分时按 AST 依赖做了拓扑排序，
每个模块只 import 排在自己前面的模块，不存在循环引用。
"""

from __future__ import annotations

from xyxbot import actions as A
from xyxbot.waiting import wait_gone, wait_until, wait_visible
from playwright.sync_api import Page

from xyxbot.books.editor import _shot, current_editor_title, is_in_editor
from xyxbot.books.list import list_books, match_books
from xyxbot.books.modal import close_activity_modal
from xyxbot.books.nav import goto_books

__all__ = ["_click_book_and_retry", "_editor_usable", "_ensure_book_url", "_try_click_book_card", "open_book"]


def _try_click_book_card(page: Page, target: dict) -> bool:
    """点作品卡：优先点卡片内的 chapters 链接（最稳），退化为点卡片本体。"""
    try:
        link = target["el"].locator("a[href*='chapters/']").first
        if link.count() and link.is_visible(timeout=1200):
            link.click(timeout=4000)
            print("[open] ✓ 点击了作品链接")
            return True
    except Exception:
        pass
    try:
        target["el"].click(timeout=4000)
        print("[open] ✓ 点击了作品卡")
        return True
    except Exception as e:
        print(f"[open] ⚠ 常规点击失败: {str(e).splitlines()[0]}")
        return False



def _click_book_and_retry(page: Page, target: dict) -> bool:
    """点作品卡；点到不了多半是被活动遮罩拦了 → 关遮罩后重试一次。"""
    ok = _try_click_book_card(page, target)
    if not ok:
        print("[open] 尝试关闭遮罩后重试 ...")
        close_activity_modal(page)
        page.keyboard.press("Escape")
        # ★ 效率改造：原来固定 sleep 0.6s 等遮罩消失。改成等遮罩不可见。
        wait_gone(lambda: page.locator(
            ".n-modal-mask, .n-modal-container").first.is_visible(timeout=60),
            timeout=2.0, interval=0.05, desc="遮罩消失")
        ok = _try_click_book_card(page, target)
    return ok



def _ensure_book_url(page: Page, target: dict, ok: bool) -> bool:
    """确认真的跳进编辑器了；没跳就走 hash 路由兜底。返回最终是否成功。

    ★★ 关键修复（2026-10-03 实测）：点击"成功"≠真的跳转了。
      有时点击作品链接后 URL 停在作品页没变（被 SPA 吞掉/弹窗拦截），
      此时 is_in_editor 会误判（作品卡里也有「新建章节」按钮）。
      → 这里校验 URL hash 是否真的变成 #/chapters/<id>，没变就强制走 goto 兜底。

    ★ 效率改造：原来是「固定 sleep 1.2s → 只检查**一次** URL」。
      这既慢（每次开作品必等 1.2 秒），又不稳（网络慢时 1.2 秒还没跳完就被
      判为失败，白白多做一次 goto 兜底）。
      现在改成**轮询等 URL 真的跳过去**：跳成就立刻继续（通常几十~几百毫秒），
      最慢等 3 秒（比原来更有耐心，所以更不容易误判）。

    ★ 现场实测（2026-10-04）：这里**每次都会走兜底** —— 点作品卡后 URL 并不变
      （站点把编辑器开在了**新标签页**里，而 App.page 永远返回 pages[0]，
      所以主页面还停在作品页）。旧代码因此每次白等满 3.0 秒才 fallback。
    ★ 再优化（2026-10-05）：既然实测"点完 URL 就是不动"，那 1.2 秒的等待基本
      是纯浪费。缩到 0.35s —— 真跳转的话（少数情况）0.35s 内早就 hash 变了；
      没跳就立刻走 goto 兜底（goto 只需 ~0.1s）。
    """
    if ok and target.get("book_id"):
        want = f"chapters/{target['book_id']}"
        pages_before = len(page.context.pages)
        hit = wait_until(lambda: want in (page.url or ""),
                         timeout=0.35, interval=0.05, desc="跳转到编辑器")
        if not hit.ok:
            extra = len(page.context.pages) - pages_before
            print("[open] ⚠ 点击后未跳转（URL 仍是作品页），改用直接跳转兜底"
                  + (f"（点击另开了 {extra} 个标签页）" if extra > 0 else ""))
            ok = False

    # 最后兜底：直接走 hash 路由（有 book_id 就一定能到）
    if not ok and target.get("book_id"):
        url = f"https://xingyuexiezuo.com/#/chapters/{target['book_id']}"
        print(f"[open] 改用直接跳转: {url}")
        try:
            page.goto(url, wait_until="domcontentloaded")
            ok = True
        except Exception as e:
            print(f"[open] ✗ 跳转失败: {e}")

    if not ok:
        _shot(page, "open_book_fail")
    return ok



def _editor_usable(page: Page) -> bool:
    """编辑器是否"下一步真的能用"（章节项 / AI续写按钮 / 正文区出现）。

    ★★★ 2026-10-05（用户指点 + 实测坐实）：
      「你只要停留的时间够，点的按钮出来就行。」

      实测踩坑（探针亲眼看到）：
        [open] ✓ 已进入作品编辑器：这里空空如也（0.00s）  ← is_in_editor 太弱
        [ai] ✗ 左栏没有章节项                            ← 章节列表还没渲染
        [ai] 点击 AI续写正文（JS 降级；原生点击被拦）      ← 点了个空壳
        [ai] 弹窗未出现，清理干扰后重试 …                 ← 白费一轮
        → 这就是用户说的「点击作品后，寻找 AI续写正文按钮的过程很长」！

      is_in_editor 只要 URL 像编辑器就返回 True，但**左栏章节/工具栏还没渲染**。
      ⇒ 这里补一段：**等"下一步要用的东西"（章节项 或 AI续写正文按钮）出现**。
         出现即走（通常几百毫秒）；等不到也不算失败——交给后面各自的
         open_chapter / open_continue_dialog 自己兜底（行为不退化）。
    """
    for sel in (".chapter-item", "button:has-text('AI续写正文')",
                ".tiptap.ProseMirror"):
        try:
            if page.locator(sel).count() > 0:
                return True
        except Exception:
            continue
    return False



def open_book(page: Page, keyword: str, index: int | None = None,
              wait: float = 3.0, console_pick: bool = False) -> bool:
    """按名字打开一个已有作品（进入它的章节编辑页）。

    Args:
        keyword:      作品名关键词（或 book_id 数字）
        index:        命中多个时选第几个（从 0 开始）；None 且命中多个 →
                      console_pick=True 时在终端问，否则直接报错返回 False
        wait:         点完之后等多久
        console_pick: 命中多个时是否在终端提示选择

    Returns:
        bool: 是否成功打开
    """
    print("=" * 58)
    print(f"  打开作品：{keyword!r}" + (f"  (index={index})" if index is not None else ""))
    print("=" * 58)

    if not goto_books(page):
        print("[open] ✗ 无法进入作品页")
        return False

    # ★★ 2026-10-05 用户指点：「你只要停留的时间够，点的按钮出来就行。」
    #   这里等的是**要用的东西**（作品卡）出现 —— 出现即走，不固定睡。
    wait_until(lambda: page.locator(
        ".book-card:not(.create-card), .create-card").count() > 0,
        timeout=max(float(wait), 3.0), interval=0.08, desc="作品卡出现")
    A.human_pause(0.1, 0.3)           # ★ 随机延迟打散节奏

    books = list_books(page)
    if not books:
        print("[open] ✗ 作品页上没有找到任何作品")
        return False

    print(f"[open] 当前共 {len(books)} 部作品：")
    for b in books:
        print(f"    [{b['index']}] {b['title']:<20s} id={b['book_id']:<10s} {b['words']}")

    hits = match_books(books, keyword)
    if not hits:
        print(f"[open] ✗ 没有匹配 {keyword!r} 的作品")
        return False

    if len(hits) > 1:
        print(f"[open] ⚠ 匹配到 {len(hits)} 个，需要消歧：")
        for i, b in enumerate(hits):
            print(f"    ({i}) {b['title']}  id={b['book_id']}  {b['created']}")

        if index is not None:
            if not (0 <= index < len(hits)):
                print(f"[open] ✗ index={index} 越界（可选 0~{len(hits)-1}）")
                return False
            target = hits[index]
        elif console_pick:
            try:
                raw = input(f"  请输入序号 [0-{len(hits)-1}]（回车取消）: ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\n[open] 已取消")
                return False
            if not raw:
                print("[open] 已取消")
                return False
            try:
                k = int(raw)
            except ValueError:
                print(f"[open] ✗ 无效输入: {raw}")
                return False
            if not (0 <= k < len(hits)):
                print(f"[open] ✗ 序号越界")
                return False
            target = hits[k]
        else:
            print(f"[open] ⚠ 命中多个但未指定 index，为安全起见中止。"
                  f"（可传 index=0~{len(hits)-1}）")
            return False
    else:
        target = hits[0]

    print(f"[open] → 打开：{target['title']}  id={target['book_id']}")

    # ★ 先把活动弹窗关掉 —— 实测它会盖满页面导致点击被拦截
    close_activity_modal(page)

    # 点击（点到不了就关遮罩重试一次）
    ok = _click_book_and_retry(page, target)
    ok = _ensure_book_url(page, target, ok)
    if not ok:
        return False

    # ★ 效率改造（2026-10-04 实测）：原来是「固定 sleep(wait=3.0) 等编辑器渲染」。
    #   实测进入编辑器只需几百毫秒，这 3 秒是纯白等。
    #   现在改成**等编辑器真的就绪**；超时用 max(wait,3)+2（比原来更宽容），
    #   所以"页面慢"的最坏情况不会比旧实现差。
    #   注意：这里**保留 wait 参数语义**——它从"固定等多久"变成"最少等到就绪"。
    print(f"[open] 当前 URL: {page.url}")

    ready = wait_until(lambda: is_in_editor(page),
                       timeout=max(float(wait), 3.0) + 2.0,
                       interval=0.08, desc="编辑器就绪")
    if not ready.ok:
        print("[open] ✗ 仍未进入编辑器（URL 或 DOM 都不像），中止")
        _shot(page, "open_book_unknown")
        return False

    got = wait_until(lambda: _editor_usable(page),
                     timeout=max(float(wait), 3.0),
                     interval=0.08, desc="编辑器可用（章节/工具栏出现）")
    t = current_editor_title(page)
    print(f"[open] ✓ 已进入作品编辑器：{t or target['title']}"
          f"（就绪 {ready.elapsed:.2f}s / 可用 {'✓' if got.ok else '✗ 超时'}）")
    A.human_pause(0.1, 0.35)          # ★ 随机延迟打散节奏

    return True

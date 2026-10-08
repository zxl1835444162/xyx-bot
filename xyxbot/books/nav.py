"""进「我的作品」页（顶部入口 / 侧栏入口）。

本文件由原巨型模块拆分而来（Phase C2/C1），拆分时按 AST 依赖做了拓扑排序，
每个模块只 import 排在自己前面的模块，不存在循环引用。
"""

from __future__ import annotations

from xyxbot import actions as A
from xyxbot import config as C
from xyxbot.waiting import wait_gone, wait_until, wait_visible
from playwright.sync_api import Page

from xyxbot.books.editor import CLICK_FAST_TIMEOUT
from xyxbot.books.modal import close_activity_modal

__all__ = ["_click_sidebar_books", "_on_books_page", "goto_books"]


# ---------------------------------------------------------------- 进入作品页

def goto_books(page: Page, wait: float = 3.0) -> bool:
    """进入「作品」列表页。

    优先点侧边栏「作品」，失败则直接走 hash 路由。
    """
    from xyxbot.login import open_site_page

    print("[books] 进入作品页 ...")

    # 已在作品页？
    if _on_books_page(page):
        print("[books] 已在作品页")
        return True

    # 先回首页再点侧边栏
    open_site_page(page, wait=2.5)

    if _on_books_page(page):
        print("[books] 已在作品页")
        return True

    # 点侧边栏「作品」
    clicked = _click_sidebar_books(page)
    if not clicked:
        # 兜底：直接走 hash 路由
        url = C.route_url("books")
        print(f"[books] 侧边栏未命中，直接打开路由 {url}")
        page.goto(url, wait_until="domcontentloaded")

    # ★★ 2026-10-05 用户指点：「你只要停留的时间够，点的按钮出来就行。」
    #   所以这里**等"下一步要用的东西"（作品卡）出现**，而不是固定睡 wait 秒。
    #   `wait` 的语义变成"最长愿意等多久"（保留参数兼容，不再是无脑睡眠）。
    #   配合一个短随机延迟打散节奏（避免机械操作被站点识别）。
    def _books_ready() -> bool:
        if _on_books_page(page):
            return True
        # 也接受"只剩 create-card 但确实在 books 路由"的情形
        try:
            if "#/books" in (page.url or "").lower():
                for sel in C.BOOK_SELECTORS["create_card"]:
                    if page.locator(sel).count() > 0:
                        return True
        except Exception:
            pass
        return False

    wait_until(_books_ready, timeout=max(float(wait), 3.0) + 3.0,
               interval=0.08, desc="作品列表出现")
    A.human_pause(0.15, 0.45)          # ★ 随机延迟：打散机械节奏
    ok = _on_books_page(page)
    if ok:
        # 进页后先把活动弹窗关掉（实测会盖满页面，导致后续点击被拦）
        close_activity_modal(page, verbose=False)
    print(f"[books] {'✓ 已进入作品页' if ok else '✗ 未能确认进入作品页'}  URL={page.url}")
    return ok



def _on_books_page(page: Page) -> bool:
    """判断当前是否在「作品列表页」——判据是**能看到作品列表的卡片**。

    ★★ 2026-10-05（用户指点）：
      「你只要停留的时间够，点的按钮出来就行。」
      ——不要纠结"页面稳没稳/URL 对不对"，只看**下一步要用的东西在不在**。

    实测拿到的关键事实：
      · 站点首页也有 `.create-card`（"开始创作"入口）⇒ **不能只看入口卡**！
        只看它会把首页误判成作品页（老代码就踩了这个坑：
         首页 → 有 .create-card → 判"已在作品页" → 不导航
         → list_books() 在首页数出 0 个作品 → 报"没有找到任何作品"）。
      · 点侧边栏「作品」**不会改 URL hash**（还是 `xingyuexiezuo.com/`）
        ⇒ **URL 也不能作判据**。

    ⇒ 唯一可靠判据：**页面上有"已有作品卡"** `.book-card:not(.create-card)`。
       （首页没有它；作品页一定有——哪怕是 0 作品的账号，
        也要靠 `#/books` 路由兜底，见下面第 ② 条。）
    """
    # ① 有已有作品卡 → 铁定是作品页
    for sel in C.BOOK_SELECTORS.get("existing_card", []):
        try:
            if page.locator(sel).count() > 0:
                return True
        except Exception:
            continue

    # ② 例外：账号下一本书都没有时，卡片数为 0 —— 这时**只能**认路由。
    #    注意：这只在"确实没有作品卡"时才用，不会把首页误判成作品页
    #    （首页会命中 ① 之外的 .create-card，但这里不认它）。
    try:
        if "#/books" in (page.url or "").lower():
            return True
    except Exception:
        pass

    return False



def _click_sidebar_books(page: Page) -> bool:
    """点侧边栏的「作品」菜单项。

    侧边栏在 `.sidebar-container` 里，精确到这个范围内找，避免点到别处。

    ★★ 2026-10-05 实测踩坑（探针里亲眼看到 15 秒超时）：
      点「作品」时被残留的 `.n-modal-mask`（活动弹窗的遮罩）拦住，
      Playwright 重试到 `Locator.click: Timeout 15000ms exceeded`。
      ⇒ 点之前**必须先清掉遮罩/活动弹窗**；点击失败也要**立刻 JS 降级**，
        别在原地死等 15 秒。
    """
    # ★ 先清活动弹窗（它留下的遮罩会拦住侧边栏点击）
    try:
        close_activity_modal(page, verbose=False)
    except Exception:
        pass

    scoped = [
        ".sidebar-container >> text=作品",
        ".sidebar-container a:has-text('作品')",
        ".sidebar-container li:has-text('作品')",
        "[class*=sidebar] >> text=作品",
    ]
    for sel in scoped:
        try:
            loc = page.locator(sel).first
            if not (loc.count() and loc.is_visible(timeout=1200)):
                continue
            # ★ 短超时原生点击 → 失败立刻 JS 降级（避免 15 秒白等）
            clicked = False
            try:
                loc.click(timeout=CLICK_FAST_TIMEOUT)
                clicked = True
            except Exception as e:
                print(f"[books] ⚠ 侧边栏原生点击失败（{str(e).splitlines()[0]}）→ JS 降级")
                try:
                    loc.evaluate("e => e.click()")
                    clicked = True
                except Exception:
                    pass
            if not clicked:
                continue
            print(f"[books] 点击侧边栏「作品」: {sel}")
            # ★ 等**作品列表渲染出来**这个可见信号（而不是固定 sleep 2.5s）
            wait_visible(page, [".book-card:not(.create-card)", ".create-card"],
                         timeout=6.0, desc="作品页就绪")
            return True
        except Exception:
            continue
    return False

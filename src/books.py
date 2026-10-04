"""作品页操作：进入作品列表、打开已有作品、新建作品。

★ 关键坑（实测于 2026-10-03）
    作品页上「新建作品」**不是一个唯一的文字**。实际存在：
        - 入口卡：一个虚线框大加号，class 含 `create-card`   ← 这才是要点的
        - 已有作品 A：名字就叫「新建作品」（用户建的作品恰好这个名字）
        - 已有作品 B：名字叫「新建作品1」

    所以：
        ❌ `text=新建作品`  → 命中 4 个，会点到别人的作品
        ✅ `.create-card`   → 唯一命中，安全

★ 第二个坑：作品名**会重复**
    实测出现过 3 部同名「自动化测试-勿动」。所以「打开某个作品」不能只靠名字，
    真正的唯一标识是卡片内的 `#/chapters/<数字ID>` 链接。
    `list_books()` 会把 ID 一起读出来，`open_book()` 做模糊匹配 + 消歧。

    本模块统一用 `click_strict` + `.create-card`，从机制上避免点错。
"""

from __future__ import annotations

import random
import time

from playwright.sync_api import Page

from . import actions as A
from . import config as C
from . import session as S
from .waiting import wait_gone, wait_until, wait_visible


# ---------------------------------------------------------------- 进入作品页

def goto_books(page: Page, wait: float = 3.0) -> bool:
    """进入「作品」列表页。

    优先点侧边栏「作品」，失败则直接走 hash 路由。
    """
    from .login import open_site_page

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
        time.sleep(wait)

    time.sleep(wait)
    ok = _on_books_page(page)
    if ok:
        # 进页后先把活动弹窗关掉（实测会盖满页面）
        close_activity_modal(page, verbose=False)
    print(f"[books] {'✓ 已进入作品页' if ok else '✗ 未能确认进入作品页'}  URL={page.url}")
    return ok


def _on_books_page(page: Page) -> bool:
    """判断当前是否在作品页（靠「新建」入口卡是否存在）。"""
    try:
        if page.locator(C.BOOK_SELECTORS["create_card"][0]).count() > 0:
            return True
    except Exception:
        pass
    try:
        return "books" in (page.url or "").lower()
    except Exception:
        return False


def _click_sidebar_books(page: Page) -> bool:
    """点侧边栏的「作品」菜单项。

    侧边栏在 `.sidebar-container` 里，精确到这个范围内找，避免点到别处。
    """
    scoped = [
        ".sidebar-container >> text=作品",
        ".sidebar-container a:has-text('作品')",
        ".sidebar-container li:has-text('作品')",
        "[class*=sidebar] >> text=作品",
    ]
    for sel in scoped:
        try:
            loc = page.locator(sel).first
            if loc.is_visible(timeout=1500):
                loc.click()
                print(f"[books] 点击侧边栏「作品」: {sel}")
                # ★ 效率改造：原来固定 sleep 2.5s 等页面切换。
                #   改成等**作品页的标志物出现**（新建入口卡 .create-card），
                #   切换完成就立刻返回（通常几百毫秒）。
                #   拿不到也不影响：调用方 goto_books 还会再兜底判断。
                wait_visible(page, [".create-card"], timeout=6.0,
                             desc="作品页就绪")
                return True
        except Exception:
            continue
    return False


# ---------------------------------------------------------------- 新建作品

def find_create_card(page: Page):
    """定位「新建作品」入口卡。返回 Locator 或 None。

    只用 `.create-card` —— 这是**唯一**能区分入口卡和已有作品卡的依据。
    """
    for sel in C.BOOK_SELECTORS["create_card"]:
        try:
            loc = page.locator(sel)
            n = loc.count()
            vis = [i for i in range(n) if loc.nth(i).is_visible()]
            if len(vis) == 1:
                return loc.nth(vis[0])
            if len(vis) > 1:
                print(f"[books] ⚠ {sel} 命中 {len(vis)} 个，取第一个")
                return loc.nth(vis[0])
        except Exception:
            continue
    return None


def count_existing_books(page: Page) -> int:
    """统计已有作品卡数量（不包含新建入口卡）。"""
    for sel in C.BOOK_SELECTORS["existing_card"]:
        try:
            n = page.locator(sel).count()
            if n:
                return n
        except Exception:
            continue
    return 0


def list_book_titles(page: Page) -> list[str]:
    """列出已有作品的标题（只取名字，轻量）。"""
    return [b["title"] for b in list_books(page)]


def list_books(page: Page) -> list[dict]:
    """列出全部已有作品，带 ID、简介、字数等。

    ★ 实测（2026-10-03）：作品名**会重复**（出现过 3 个「自动化测试-勿动」），
      所以光靠名字无法唯一定位。真正的唯一标识是卡片内的
      `#/chapters/<数字ID>` 链接 —— 这里一并读出来。

    Returns:
        [{"index":0, "title":"xx", "book_id":"2368291", "intro":"yy",
          "words":"0字", "created":"刚刚", "el":Locator}, ...]
    """
    out: list[dict] = []
    try:
        cards = page.locator(".book-card:not(.create-card)")
        n = cards.count()
    except Exception:
        return out

    for i in range(n):
        c = cards.nth(i)
        try:
            info = c.evaluate("""el => {
                const q = s => el.querySelector(s);
                const t = q('.n-thing-header__title');
                const a = el.querySelector('a[href*="chapters/"]')
                       || el.querySelector('a[href]');
                const txt = (el.innerText||'').trim().split('\\n')
                              .map(s=>s.trim()).filter(Boolean);
                return {
                    title: t ? (t.innerText||'').trim() : (txt[0]||''),
                    href : a ? a.getAttribute('href') : '',
                    lines: txt
                };
            }""")
        except Exception:
            continue

        href = info.get("href") or ""
        book_id = ""
        if "chapters/" in href:
            book_id = href.split("chapters/")[-1].split("/")[0].split("?")[0]

        lines = info.get("lines") or []
        title = (info.get("title") or "").strip()

        # 从卡片文本里挑简介/字数/创建时间（位置固定：标题|简介|类型|字数|创建于）
        intro = ""
        words = ""
        created = ""
        for s in lines:
            if s == title:
                continue
            if "字" in s and len(s) < 12:
                words = words or s
            elif s.startswith("创建于"):
                created = s.replace("创建于:", "").replace("创建于：", "")
            elif not intro and s not in ("小说", "剧本"):
                intro = s

        out.append({
            "index": i,
            "title": title,
            "book_id": book_id,
            "intro": intro,
            "words": words,
            "created": created,
            "el": c,
        })
    return out


def match_books(books: list[dict], keyword: str) -> list[dict]:
    """按关键词筛选作品。

    匹配优先级：完全相等 > 开头匹配 > 包含匹配（大小写不敏感）。
    若关键词就是纯数字，则优先按 book_id 匹配。
    """
    kw = (keyword or "").strip()
    if not kw:
        return []

    # 纯数字 → 先按 ID
    if kw.isdigit():
        by_id = [b for b in books if b.get("book_id") == kw]
        if by_id:
            return by_id

    low = kw.lower()
    exact = [b for b in books if b["title"] == kw]
    if exact:
        return exact
    start = [b for b in books if b["title"].lower().startswith(low)]
    if start:
        return start
    return [b for b in books if low in b["title"].lower()]


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

    # 点击：优先点卡片内的 chapters 链接（最稳），退化为点卡片本体
    def _try_click() -> bool:
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

    ok = _try_click()

    # 被弹窗拦截 → 关弹窗重试
    if not ok:
        print("[open] 尝试关闭遮罩后重试 ...")
        close_activity_modal(page)
        page.keyboard.press("Escape")
        # ★ 效率改造：原来固定 sleep 0.6s 等遮罩消失。改成等遮罩不可见。
        wait_gone(lambda: page.locator(
            ".n-modal-mask, .n-modal-container").first.is_visible(timeout=60),
            timeout=2.0, interval=0.05, desc="遮罩消失")
        ok = _try_click()

    # ★★ 关键修复（2026-10-03 实测）：点击"成功"≠真的跳转了。
    #   有时点击作品链接后 URL 停在作品页没变（被 SPA 吞掉/弹窗拦截），
    #   此时 is_in_editor 会误判（作品卡里也有「新建章节」按钮）。
    #   → 这里校验 URL hash 是否真的变成 #/chapters/<id>，没变就强制走 goto 兜底。
    #
    # ★ 效率改造（本轮）：原来是「固定 sleep 1.2s → 只检查**一次** URL」。
    #   这既慢（每次开作品必等 1.2 秒），又不稳（网络慢时 1.2 秒还没跳完就被
    #   判为失败，白白多做一次 goto 兜底）。
    #   现在改成**轮询等 URL 真的跳过去**：跳成就立刻继续（通常几十~几百毫秒），
    #   最慢等 3 秒（比原来更有耐心，所以更不容易误判）。
    if ok and target.get("book_id"):
        want = f"chapters/{target['book_id']}"
        # ★ 现场实测（2026-10-04）：这里**每次都会走兜底** ——
        #   点作品卡后 URL 并不变（站点把编辑器开在了**新标签页**里，
        #   而 App.page 永远返回 pages[0]，所以主页面还停在作品页）。
        #   旧代码因此每次白等满 3.0 秒才 fallback。现在：
        #     - 轮询窗口缩到 1.2 秒（真跳了就立刻继续，没跳就快速兜底）
        #     - 同时把「有没有多开标签页」记下来，方便排查
        pages_before = len(page.context.pages)
        hit = wait_until(lambda: want in (page.url or ""),
                         timeout=1.2, interval=0.05, desc="跳转到编辑器")
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
    if ready.ok:
        t = current_editor_title(page)
        print(f"[open] ✓ 已进入作品编辑器：{t or target['title']}"
              f"（{ready.elapsed:.2f}s）")
    else:
        print("[open] ✗ 仍未进入编辑器（URL 或 DOM 都不像），中止")
        _shot(page, "open_book_unknown")
        return False

    return True


def click_create_book(page: Page, wait: float = 2.0) -> bool:
    """点击「新建作品」入口卡。

    安全策略：
        1. 先打印现场（有几张已有作品卡、都叫什么）
        2. 只用 `.create-card` 精确定位（绝不使用文本匹配）
        3. 用 click_strict 兜底，命中多个就拒绝点击
    """
    print("[books] --- 新建作品 ---")

    # 先清掉活动弹窗（会遮挡入口卡，导致点击降级或失败）
    close_activity_modal(page, verbose=False)

    existing = count_existing_books(page)
    titles = list_book_titles(page)
    print(f"[books] 当前已有作品 {existing} 个: {titles}")
    print("[books] ⚠ 注意：已有作品里可能就有叫「新建作品」的，"
          "因此不使用文字匹配，改用 .create-card 精确定位")

    card = find_create_card(page)
    if card is None:
        print("[books] ✗ 找不到「新建作品」入口卡（.create-card）")
        p = C.SHOTS / f"fail-create-card-{int(time.time())}.png"
        page.screenshot(path=str(p), full_page=True)
        print(f"[books] 已截图 {p}")
        return False

    # 校验：确认拿到的是入口卡，而不是已有作品卡
    try:
        cls = card.get_attribute("class") or ""
        if "create-card" not in cls:
            print(f"[books] ✗ 定位到的元素 class 不含 create-card: {cls}")
            return False
        print(f"[books] ✓ 定位到入口卡，class={cls}")
    except Exception as e:
        print(f"[books] 校验 class 失败: {e}")

    # 点击（click_strict 再兜一层）
    ok = A.click_strict(
        page,
        C.BOOK_SELECTORS["create_card"],
        label="新建作品入口卡",
        expect_unique=True,
    )
    if not ok:
        return False

    time.sleep(wait)
    print(f"[books] 点击后 URL: {page.url}")
    return True


def close_activity_modal(page: Page, verbose: bool = True) -> bool:
    """关掉可能挡住页面的活动弹窗（邀请好友 / 大奖赛 / 国庆特惠等）。

    实测（2026-10-03）：进入作品页后会自动弹出「邀请好友赚佣金大奖赛」，
    里面是个 `n-data-table` 排行榜，**整个弹窗盖满页面**，
    导致后续所有点击被 `intercepts pointer events` 拦截。

    策略：
        1. 只关「活动类」弹窗 —— 用标题文字识别，绝不误关「新建作品」弹窗
        2. 逐个尝试 close 按钮 / 「不再弹出」/ ESC 兜底
    """
    # 活动弹窗的标题特征（绝不能包含「作品名称」「创建作品」）
    activity_marks = [
        ":has-text('邀请好友')",
        ":has-text('赚佣金')",
        ":has-text('大奖赛')",
        ":has-text('打卡挑战')",
        ":has-text('特惠')",
    ]
    # 排除新建作品弹窗
    not_create = ":not(:has-text('作品名称'))"

    closed = False
    for mark in activity_marks:
        try:
            modal = page.locator(f".n-modal{mark}{not_create}").first
            if not modal.is_visible(timeout=600):
                continue
        except Exception:
            continue

        if verbose:
            print(f"[books] 发现活动弹窗 {mark}，尝试关闭 ...")

        # a) 优先精确的 close 按钮
        for closer in ("button[aria-label='close']", ".n-base-close",
                       "[class*=close]", "text=×"):
            try:
                btn = modal.locator(closer).first
                if btn.is_visible(timeout=500):
                    btn.click(timeout=2000)
                    closed = True
                    if verbose:
                        print(f"[books]   已点关闭按钮 ({closer})")
                    time.sleep(0.7)
                    break
            except Exception:
                continue

        # b) 「不再弹出」这类文字按钮
        if not closed:
            for txt in ("text=不再弹出", "text=不再提醒", "text=关闭"):
                try:
                    btn = modal.locator(txt).first
                    if btn.is_visible(timeout=400):
                        btn.click(timeout=2000)
                        closed = True
                        if verbose:
                            print(f"[books]   已点「{txt}」")
                        time.sleep(0.7)
                        break
                except Exception:
                    continue

        # c) 兜底：ESC
        if not closed:
            try:
                page.keyboard.press("Escape")
                time.sleep(0.7)
                closed = True
                if verbose:
                    print("[books]   已按 ESC 关闭")
            except Exception:
                pass

        if closed:
            break

    # 最终确认：活动弹窗还在不在
    if closed:
        time.sleep(0.5)
        still = False
        for mark in activity_marks:
            try:
                if page.locator(f".n-modal{mark}{not_create}").first.is_visible(timeout=400):
                    still = True
                    break
            except Exception:
                continue
        if verbose:
            print("[books] 活动弹窗" + ("⚠ 仍然存在" if still else "✓ 已清除"))
        return not still

    return closed


def open_create_dialog(page: Page, timeout: float = 8.0) -> bool:
    """等待「新建作品」弹窗出现。

    实测弹窗特征：标题「创建作品后可使用AI功能」，含「作品名称」「作品类型」。
    """
    print("[books] 等待新建作品弹窗 ...")
    deadline = time.time() + timeout
    while time.time() < deadline:
        for sel in C.BOOK_SELECTORS["create_dialog"]:
            try:
                if page.locator(sel).first.is_visible(timeout=800):
                    print(f"[books] ✓ 弹窗出现: {sel}")
                    return True
            except Exception:
                continue
        time.sleep(0.5)
    print("[books] ⚠ 未检测到新建作品弹窗（可能直接进入编辑器）")
    return False


def fill_book_title(page: Page, title: str) -> bool:
    """在弹窗里填作品名称。

    实测：输入框默认值就是「新建作品」，上限 30 字。
    """
    if not title:
        return True
    for sel in C.BOOK_SELECTORS["dialog_title_input"]:
        try:
            loc = page.locator(sel).first
            if not loc.is_visible(timeout=1200):
                continue
            loc.click()
            loc.fill("")               # 清掉默认的「新建作品」
            A.human_pause(0.1, 0.25)
            for ch in title:
                loc.type(ch, delay=random.randint(50, 130))
            val = loc.input_value()
            print(f"[books] ✓ 作品名称已填: {val!r}  (选择器={sel})")
            return val.strip() == title.strip()
        except Exception as e:
            print(f"[books] 填标题失败 ({sel}): {str(e)[:60]}")
            continue
    print("[books] ⚠ 没找到作品名称输入框")
    return False


def select_book_type(page: Page, kind: str = "novel") -> bool:
    """选择作品类型。kind: 'novel'(小说) / 'script'(剧本)。

    实测默认已选中「小说」，所以只在需要剧本时才真的点。
    """
    if kind not in ("novel", "script"):
        return False

    key = "dialog_type_novel" if kind == "novel" else "dialog_type_script"
    label = "小说" if kind == "novel" else "剧本"

    for sel in C.BOOK_SELECTORS[key]:
        try:
            loc = page.locator(sel).first
            if loc.is_visible(timeout=1200):
                loc.click()
                print(f"[books] ✓ 已选择作品类型: {label}")
                A.human_pause(0.2, 0.5)
                return True
        except Exception:
            continue
    print(f"[books] ⚠ 未能选择类型 {label}（可能默认已是）")
    return False


def submit_create(page: Page, wait: float = 4.0) -> bool:
    """点「提交」完成创建。"""
    ok = A.click(page, C.BOOK_SELECTORS["dialog_confirm_btn"],
                 label="提交（创建作品）", shot_on_fail=False)
    if ok:
        print("[books] 已提交，等待创建完成 ...")
        time.sleep(wait)
    return ok


_shot_counter = 0


def _shot(page: Page, name: str) -> None:
    """存截图到 artifacts/screenshots/，失败不影响主流程。"""
    global _shot_counter
    try:
        out = C.SHOTS / f"{name}.png"
        out.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(out), full_page=False)
        print(f"[shot] {out}")
    except Exception as e:
        print(f"[shot] 截图失败: {e}")
    _shot_counter += 1


# ------------------------------------------------------------ 编辑器判定

# 编辑器特征：顶部 AI 工具栏 / 左侧章节树 / 正文区
EDITOR_MARKS = [
    "text=新建章节",
    "text=请输入章节内容",
    "[class*=editor]",
    "[class*=chapter]",
]


def is_in_editor(page: Page) -> bool:
    """当前是否已进入作品编辑器。

    实测（2026-10-03）：
      - 编辑器路由 = `#/chapters/<id>`（hash 路由）
      - ★★ 坑：**作品列表页每张作品卡里也有「新建章节」按钮**，
        所以不能用 `text=新建章节` 判定（会误判作品页为编辑器）。
        必须用「hash 路由」或「有章节树 + 无作品卡」来判定。
    """
    url = (page.url or "").lower()

    # 1) ★ 最可靠：hash 路由特征
    if "#/chapters/" in url or "#/write" in url or "#/editor" in url:
        return True

    # 2) 次可靠：有章节树（.chapter-item）且**没有**作品卡列表
    try:
        has_chapters = page.locator(".chapter-item").count() > 0
        has_book_cards = page.locator(".book-card:not(.create-card)").count() > 0
        if has_chapters and not has_book_cards:
            return True
    except Exception:
        pass

    return False


def current_editor_title(page: Page) -> str:
    """读编辑器左上角的作品名（读不到返回空串）。"""
    sels = [
        "[class*=book-title]",
        "[class*=bookTitle]",
        "[class*=header] [class*=title]",
        "[class*=name]",
    ]
    for sel in sels:
        try:
            loc = page.locator(sel).first
            if loc.is_visible(timeout=600):
                t = (loc.inner_text(timeout=400) or "").strip()
                if t and len(t) < 40:
                    return t
        except Exception:
            continue
    return ""


# ---------------------------------------------------------------- 组合流程

def create_book(page: Page, title: str = "", book_type: str = "novel",
                intro: str = "", submit: bool = True) -> bool:
    """完整流程：进作品页 → 关广告弹窗 → 点「+ 新建作品」入口卡 → 填表单 → 提交。

    关键点：入口卡用 `.create-card` 精确定位，
    绝不能用 `text=新建作品` —— 站点上已有作品可能就叫「新建作品1」「新建作品」，
    纯文本匹配会命中多个（实测命中 4 个），必然误点。

    Args:
        title:     作品名；留空则用站点默认（弹窗内已有默认值「新建作品」）
        book_type: "novel" 小说 / "script" 剧本
        intro:     作品简介（选填，站点上限 500 字）
        submit:    是否点击「提交」创建；False 则只填完表单停下（调试用）

    Returns:
        bool: 是否成功走完创建流程
    """
    print("=" * 58)
    print("  新建作品流程开始")
    print(f"    标题   = {title or '（站点默认）'}")
    print(f"    类型   = {'小说' if book_type == 'novel' else '剧本'}")
    print(f"    简介   = {intro or '（留空）'}")
    print(f"    提交   = {submit}")
    print("=" * 58)

    # ① 进作品页
    if not goto_books(page):
        print("[books] ✗ 无法进入作品页，终止")
        return False

    # ② 记录创建前的基线（用于事后校验）
    before = count_existing_books(page)
    before_titles = list_book_titles(page)
    print(f"[books] 创建前：{before} 部作品 {before_titles}")

    # ③ 关掉可能挡住入口卡的运营/活动弹窗
    close_activity_modal(page)

    # ④ 点入口卡（严格模式，只用 .create-card）
    if not click_create_book(page):
        print("[books] ✗ 点击「新建作品」入口卡失败，终止")
        return False

    # ⑤ 等创建弹窗出现
    if not open_create_dialog(page, timeout=8.0):
        print("[books] ✗ 创建弹窗未出现（可能直接进了编辑器，或弹窗结构变了）")
        print(f"[books] 当前 URL: {page.url}")
        _shot(page, "create_dialog_missing")
        return False

    # ⑥ 填标题：留空就用站点默认，不动它
    if title:
        if fill_book_title(page, title):
            print(f"[books] ✓ 标题已填: {title}")
        else:
            print("[books] ⚠ 没找到标题输入框，将使用站点默认名")
    else:
        print("[books] 未指定标题，保留弹窗默认值")

    # ⑦ 选类型
    select_book_type(page, book_type)

    # ⑧ 填简介（选填）
    if intro:
        if A.fill(page, C.BOOK_SELECTORS["dialog_intro_input"],
                  intro, label="作品简介"):
            print("[books] ✓ 简介已填")
        else:
            print("[books] ⚠ 简介输入框未找到，跳过")

    # ⑨ 提交
    if not submit:
        print("[books] submit=False，表单已填好，停在弹窗前（调试模式）")
        _shot(page, "create_dialog_filled")
        return True

    if not submit_create(page, wait=4.0):
        print("[books] ✗ 提交失败")
        _shot(page, "create_submit_fail")
        return False

    # ⑩ 校验：实测提交后会直接跳进新作品的编辑器，所以要先判断跳转
    time.sleep(2.5)
    print(f"[books] 当前 URL: {page.url}")

    # ★ 实测结论（2026-10-03）：提交成功后 SPA 会跳到编辑器，
    #   原来的作品卡列表从 DOM 上消失，此时 list_book_titles 必然返回 []，
    #   绝不能因此判定「创建失败」。
    if is_in_editor(page):
        title = current_editor_title(page)
        print(f"[books] ✓ 已进入编辑器，当前作品: {title or '（读不到标题）'}")
        print("[books] ✓ 新建成功（编辑器直达，不回到作品页）")
        return True

    # 没跳编辑器 → 应该还在作品页，比对作品数
    after = count_existing_books(page)
    after_titles = list_book_titles(page)
    print(f"[books] 作品数: {before} → {after}")
    print(f"[books] 作品列表: {after_titles}")

    new_ones = [t for t in after_titles if t not in before_titles]
    if new_ones:
        print(f"[books] ✓ 新增作品: {new_ones}")
        return True

    # 兜底：可能跳到了别的路由，回去看一眼
    B_goto = goto_books(page, wait=3.0)
    if B_goto:
        after_titles = list_book_titles(page)
        new_ones = [t for t in after_titles if t not in before_titles]
        if new_ones:
            print(f"[books] ✓ 新增作品（返回作品页后确认）: {new_ones}")
            return True

    print("[books] ⚠ 未检测到新增作品，请查看截图确认")
    _shot(page, "create_verify_unknown")
    return False

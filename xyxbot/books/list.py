"""列出作品、匹配与计数（含「新建作品」入口卡定位）。

本文件由原巨型模块拆分而来（Phase C2/C1），拆分时按 AST 依赖做了拓扑排序，
每个模块只 import 排在自己前面的模块，不存在循环引用。
"""

from __future__ import annotations

from xyxbot import config as C
from playwright.sync_api import Page

__all__ = ["count_existing_books", "find_create_card", "list_book_titles", "list_books", "match_books"]


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

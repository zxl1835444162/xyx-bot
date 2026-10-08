"""编辑器判定与截图小工具（★ _shot 与其计数器必须同模块）。

本文件由原巨型模块拆分而来（Phase C2/C1），拆分时按 AST 依赖做了拓扑排序，
每个模块只 import 排在自己前面的模块，不存在循环引用。
"""

from __future__ import annotations

from xyxbot import config as C
from playwright.sync_api import Page

__all__ = ["CLICK_FAST_TIMEOUT", "EDITOR_MARKS", "_shot", "_shot_counter", "current_editor_title", "is_in_editor"]

# ★ 原生点击首试超时（毫秒）。站点残留遮罩常让原生点击永远失败（重试到超时），
#   所以给短超时 + JS 降级 —— 与 src/ai.py 的 CLICK_FAST_TIMEOUT 同一策略。
CLICK_FAST_TIMEOUT = 600



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

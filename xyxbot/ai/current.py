"""读取页面上的「当前值」（当前模型 / 档位 / 快捷指令 / 审稿要求 / 关联章数）。

本文件由 `xyxbot/ai.py` 拆分而来（Phase C1）。拆分时按 AST 依赖做了拓扑排序，
所以每个模块只 import 排在自己前面的模块，不存在循环引用。
"""

from __future__ import annotations

from playwright.sync_api import Page

from xyxbot.ai.selectors import AI_SELECTORS, ASSOCIATE_MARKS

__all__ = ["_text_of", "current_associate_level", "current_model", "current_review_requirement", "current_shortcut"]

def current_model(page: Page, container: str = ".n-modal") -> str:
    """回读顶部模型选择器当前显示的名字（如「细腻版」「奇想版」）。

    ★ container：模型面板所在容器。
      - 续写：默认 ".n-modal"
      - 审稿：".n-card-content:has-text('待审文本')"
    """
    try:
        return _text_of(page.locator(f"{container} .n-base-selection"),
                        timeout=400)
    except Exception:
        return ""

def _text_of(loc, timeout: float = 300) -> str:
    """安全读文本：元素不存在时**立刻**返回空串。

    ★★ 为什么必须有这个工具（2026-10-04 实测抓到的最大性能黑洞）：
       本项目在 browser.py 里设了 `context.set_default_timeout(15000)`。
       于是 `loc.first.inner_text()`（不传 timeout）在**元素不存在**时
       不会马上失败，而是**一直等到 15 秒**才抛异常：

            locator('.__nope__').first.inner_text()          → 15009ms
            locator('.__nope__').first.inner_text(timeout=150)→   157ms
            locator('.__nope__').first.is_visible()          →     2ms

       即：**一次裸的 inner_text() 写错选择器 = 白等 15 秒**，而且是静默的
       （被 try/except 吞掉，只是"读不到"）。
       实测代价：`current_associate_level` 3 次调用 = 45.03 秒（15.01s/次）。

       所以：先 `count()`（~2ms）判断存在性，再带小超时读文本。
    """
    try:
        if not loc.count():
            return ""
        return (loc.first.inner_text(timeout=timeout) or "").strip()
    except Exception:
        return ""

def current_associate_level(page: Page) -> str:
    """回读当前「联想能力」档位（如「正常」）。读不到返回空串。

    ★★ 15 秒黑洞修复（2026-10-04 实测）：
       原实现 `page.locator("[class*=association-level]").first.inner_text()`
       **没传 timeout**。而该选择器只在**滑块浮层打开时**才存在
       （实测：浮层没开时 `count()==0`），元素不在就等到默认 15 秒。
       它在 `select_model` 里是**打开浮层之前**调用的，
       所以**每章必吃 15.0 秒**。现在改成 ~2ms 返回空串。
    """
    txt = _text_of(page.locator("[class*=association-level]"), timeout=400)
    if not txt:
        return ""
    # 形如「正常 · 0.7 | 专业 · 0.1 | …」，取第一个档位名
    first = txt.split("|")[0].strip().replace("\n", " ")
    for mark in ASSOCIATE_MARKS:
        if mark in first:
            return mark
    return ""

def current_shortcut(page: Page) -> str:
    """回读「快捷选项」那一行当前显示的提示词名字。"""
    return _text_of(page.locator(AI_SELECTORS["shortcut_row"][0]),
                    timeout=400)

def current_review_requirement(page: Page) -> str:
    """回读「审稿要求」那一行当前显示的提示词名。"""
    try:
        sels = page.locator(AI_SELECTORS["review_selects"][0])
        if sels.count() >= 2:
            return _text_of(sels.nth(1), timeout=400)
    except Exception:
        pass
    return ""

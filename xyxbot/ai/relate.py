"""「关联最近 N 章」。

本文件由 `xyxbot/ai.py` 拆分而来（Phase C1）。拆分时按 AST 依赖做了拓扑排序，
所以每个模块只 import 排在自己前面的模块，不存在循环引用。
"""

from __future__ import annotations

from xyxbot.waiting import wait_gone, wait_until, wait_visible
from playwright.sync_api import Page
import re
import time

from xyxbot.ai.current import _text_of
from xyxbot.ai.elements import _shot
from xyxbot.ai.selectors import RELATE_DROPDOWN_SEL, _CONTINUE_MODAL_SEL

__all__ = ["_relate_dropdown", "_relate_dropdown_in", "_relate_scope_roots", "_scroll_relate_into_view", "current_relate_count", "relate_chapters"]

def _relate_scope_roots(page: Page):
    """按优先级返回「应该在哪些容器里找关联下拉」的 Locator 列表。

    ① 当前续写弹窗（含「开始 AI 续写」按钮）—— 最准
    ② 全页（None）—— 兜底
    """
    roots = []
    try:
        cur = page.locator(_CONTINUE_MODAL_SEL)
        for i in range(min(cur.count(), 3)):
            c = cur.nth(i)
            try:
                if c.is_visible(timeout=120):
                    roots.append(c)
                    break            # 只要最靠前的那个可见弹窗
            except Exception:
                continue
    except Exception:
        pass
    roots.append(None)               # None = 全页兜底
    return roots

def _relate_dropdown_in(root):
    """在给定容器里找「最近N章 ⌄」下拉按钮（root=None → 全页）。"""
    # 主路径：Tailwind 的 overflow-hidden 类把下拉按钮和「最近3章」区分开
    try:
        cands = root.locator(RELATE_DROPDOWN_SEL).filter(
            has_text=re.compile(r"^最近\d+章$"))
        n = cands.count()
        for i in range(n):
            b = cands.nth(i)
            try:
                if b.is_visible(timeout=60):
                    return b
            except Exception:
                continue
        if n:
            return cands.first
    except Exception:
        pass

    # 兜底：任何"文字是 最近N章 且带 svg"的 button（排除无 svg 的「最近3章」）
    try:
        allb = root.locator(".n-modal button" if root is None
                            else "button")
        for i in range(allb.count()):
            b = allb.nth(i)
            try:
                if b.locator("svg").count() == 0:
                    continue
                if re.fullmatch(r"最近\d+章", _text_of(b, timeout=300)):
                    return b
            except Exception:
                continue
    except Exception:
        pass
    return None

def _relate_dropdown(page: Page):
    """定位「最近N章 ⌄」下拉按钮（找不到返回 None）。只读，不点击。

    ★ 优先在**当前续写弹窗**里找，避免读到残留弹窗的旧档位（见上方说明）。
    """
    for root in _relate_scope_roots(page):
        b = _relate_dropdown_in(root)
        if b is not None:
            return b
    return None

def current_relate_count(page: Page) -> int:
    """回读「关联章节」当前档位。

    Returns:
        N（当前是「最近N章」）、0（清空/未选择）、-1（读不到按钮）
    """
    b = _relate_dropdown(page)
    if b is None:
        return -1
    m = re.search(r"最近(\d+)章", _text_of(b, timeout=400))
    return int(m.group(1)) if m else -1

def _scroll_relate_into_view(page: Page) -> None:
    """把「关联章节」按钮组滚进视口（它永远在弹窗最底部）。

    替代原来「鼠标移到 (640,400) 再滚轮 12×320 = 1.2 秒」的写法 ——
    那个写法还依赖鼠标正好落在弹窗的滚动容器上，不靠谱。
    """
    try:
        loc = page.locator(".n-modal .n-scrollbar-container").first
        loc.evaluate("e => { e.scrollTop = e.scrollHeight; }")
    except Exception:
        pass

def relate_chapters(page: Page, count: int = 10, force: bool = False,
                    _retried: bool = False) -> bool:
    """关联最近 N 章。

    流程：定位「最近N章 ⌄」按钮 → （已是目标档就跳过）→ 点箭头展开菜单
          → 点「最近{count}章」→ **回读按钮文字**确认生效。

    Args:
        count: 目标档位（3 / 5 / 8 / 10 …）
        force: 即使已经是目标档也重设一遍（默认 False）

    ★ 效率（2026-10-04 实测口径）：已是对应档位时 **0 秒 0 点击**；
      需要切换时约 0.3~0.6 秒（原来固定 6.2 秒，且第 2 章起必失败）。

    ★★ 2026-10-06 加固（用户问「每次生成都选了最近十章吗？为什么这次没选上」）：
      1. 下拉按钮**只在当前续写弹窗里找**（`_relate_dropdown`），
         避免读到上一章残留弹窗的旧档位 ⇒ 误判"已是10章"而静默跳过
      2. 回读要求**连续两次**一致（防菜单开着时的假命中）
      3. 失败会自动**重试一轮**（关掉菜单重新展开）
    """
    print(f"[ai] --- 关联最近 {count} 章 ---")

    btn = _relate_dropdown(page)
    if btn is None:
        # 关联章节区在弹窗最底部，可能还没渲染出来 → 滚下去再找一次
        _scroll_relate_into_view(page)
        btn = _relate_dropdown(page)
    if btn is None:
        print("[ai] ✗ 找不到「最近N章」下拉按钮（关联章节区没展开？）")
        _shot(page, "ai_relate_missing")
        return False

    # ★ 幂等：已经是目标档位 → 直接成功，不点也不等
    #   ★★ 但要**再确认一次**（两次读数一致才敢跳过）：
    #      "跳过"是最危险的分支 —— 读错了就会带着站点默认档位（最近5章）
    #      去生成，而且日志上完全看不出异常。宁可多花 1 次只读判断。
    cur = current_relate_count(page)
    if cur == count and not force:
        if current_relate_count(page) == count:
            print(f"[ai] ✓ 关联章节已是「最近{count}章」，跳过（0 点击）")
            return True
        print(f"[ai] ⚠ 档位读数不稳（读到「最近{cur}章」但再读不一致）"
              "→ 不敢跳过，重设一遍")
        cur = current_relate_count(page)      # 重新读一个真实值用于日志

    try:
        btn.scroll_into_view_if_needed(timeout=1500)
    except Exception:
        pass

    print(f"[ai] 当前「最近{cur}章」→ 目标「最近{count}章」，展开菜单 …")

    # ① 点箭头展开菜单（点主体会直接应用当前档，不是我们要的）
    clicked = False
    try:
        btn.locator("svg").first.click(timeout=2500)
        clicked = True
    except Exception as e:
        print(f"[ai] ⚠ 点箭头失败：{str(e).splitlines()[0]}，改用坐标")
    if not clicked:
        try:
            fb = btn.bounding_box()
            if not fb:
                print("[ai] ✗ 拿不到下拉按钮位置")
                return False
            page.mouse.click(fb["x"] + fb["width"] - 14,
                             fb["y"] + fb["height"] / 2)
        except Exception as e2:
            print(f"[ai] ✗ 箭头点击失败：{e2}")
            return False

    # ② 等选项出现。
    #    ★ 这里用 `最近{count}章` 是**安全**的：菜单收起时该文字不存在；
    #      菜单打开时按钮上的文字是「最近{cur}章」且 cur != count，
    #      所以这个文字唯一指向菜单项。（旧代码用固定的"最近5章"当锚点才出错。）
    target = page.locator(f"text=最近{count}章").first
    opened = wait_until(
        lambda: bool(target.count()) and target.is_visible(timeout=60),
        timeout=4.0, interval=0.04, desc=f"菜单出现「最近{count}章」").ok
    if not opened:
        print(f"[ai] ✗ 菜单没能展开（没有「最近{count}章」选项）")
        _shot(page, "ai_count_option_missing")
        return False

    # ③ 点选项（常规点击失败就 JS 点击降级，别白等 5 秒）
    try:
        target.click(timeout=2500)
    except Exception as e:
        print(f"[ai] ⚠ 常规点击失败（{str(e).splitlines()[0]}），改用 JS 点击")
        try:
            target.evaluate("e => e.click()")
        except Exception as e2:
            print(f"[ai] ✗ 点「最近{count}章」失败：{e2}")
            _shot(page, "ai_count_option_missing")
            return False

    # ④ ★ 成败判据 = **回读按钮文字**（不再用"等菜单收起"那种必然超时的判据）
    #    ★★ 2026-10-06 加固：要求**连续两次**读数都等于目标档才算数。
    #       原因：菜单还开着的那一刻，列表里的「最近10章」选项也可能被
    #       `最近\d+章` 的文本匹配到 ⇒ 单次读数可能是**假命中**
    #       （看着"已选上"，其实设置没生效）。连续两次一致就基本排除了。
    _hit = [0]

    def _confirmed() -> bool:
        if current_relate_count(page) == count:
            _hit[0] += 1
        else:
            _hit[0] = 0
        return _hit[0] >= 2

    res = wait_until(_confirmed, timeout=3.0, interval=0.08,
                     desc=f"档位回读=最近{count}章")
    if res.ok:
        print(f"[ai] ✓ 已选「最近{count}章」"
              f"（回读确认 ×2，{res.elapsed:.2f}s）")
        return True

    # ★ 一次没成 → 关掉菜单、重试一轮（菜单状态不对时重试往往就好）
    if not _retried:
        print("[ai] ⚠ 档位没生效 → 关掉菜单重试一次")
        try:
            page.keyboard.press("Escape")
        except Exception:
            pass
        time.sleep(0.3)
        if relate_chapters(page, count=count, force=True, _retried=True):
            return True

    now = current_relate_count(page)
    print(f"[ai] ✗ 点了「最近{count}章」但档位没生效（当前 "
          f"{'最近%d章' % now if now > 0 else '读不到'}）"
          "★ 本次生成将用**站点默认档位**，前文关联会变弱")
    _shot(page, "ai_count_option_missing")
    return False

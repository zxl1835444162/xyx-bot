"""人类化操作助手：点击、输入、等待，带多选择器回退与随机延迟。

设计原则：
  1. 一个动作给多个候选选择器，按顺序试 —— DOM 改版不至于全废
  2. 动作之间加随机延迟 —— 别像机器一样瞬发
  3. 失败时自动截图 —— 方便定位
"""

from __future__ import annotations

import random
import time
from typing import Sequence

from playwright.sync_api import Locator, Page, TimeoutError as PWTimeout

from . import config as C


def human_pause(a: float = 0.25, b: float = 0.9) -> None:
    """随机停顿，模拟人手速。"""
    time.sleep(random.uniform(a, b))


def pick(page: Page, selectors: Sequence[str], timeout: int | None = None) -> Locator | None:
    """返回第一个可用（存在且可见）的元素。"""
    t = timeout or C.DEFAULT_TIMEOUT
    for sel in selectors:
        try:
            loc = page.locator(sel).first
            loc.wait_for(state="visible", timeout=t)
            return loc
        except Exception:
            continue
    return None


def click(page: Page, selectors: Sequence[str], *, timeout: int | None = None,
          label: str = "", shot_on_fail: bool = True) -> bool:
    """点击第一个命中的元素。支持传单个字符串或列表。"""
    sels = [selectors] if isinstance(selectors, str) else list(selectors)
    name = label or sels[0]
    loc = pick(page, sels, timeout)
    if loc is None:
        print(f"[click] ✗ 找不到: {name}  候选={sels}")
        if shot_on_fail:
            p = C.SHOTS / f"fail-click-{int(time.time())}.png"
            page.screenshot(path=str(p), full_page=True)
            print(f"[click] 已截图 {p}")
        return False
    try:
        loc.scroll_into_view_if_needed()
        human_pause(0.1, 0.35)
        loc.click(timeout=timeout or C.DEFAULT_TIMEOUT)
        print(f"[click] ✓ {name}")
        human_pause()
        return True
    except PWTimeout:
        # 被遮挡时退化为 JS 点击
        try:
            loc.evaluate("el => el.click()")
            print(f"[click] ✓ {name} (js 降级)")
            return True
        except Exception as e:
            print(f"[click] ✗ {name} 失败: {e}")
            return False


def click_strict(page: Page, selectors: Sequence[str], *, label: str = "",
                 expect_unique: bool = True, timeout: int | None = None,
                 shot_on_fail: bool = True) -> bool:
    """严格点击：命中多个时**拒绝点击**，只点唯一命中的那个。

    用于「页面上有多个相似元素，点错就出事」的场景。
    例如作品页里：新建入口卡 vs 名字叫「新建作品」的已有作品卡。

    Args:
        expect_unique: True 时，若单条选择器命中 >1 个可见元素则视为不安全，
                       跳过该选择器继续试下一条；全部不安全则放弃并截图。
    Returns:
        bool 是否点击成功
    """
    sels = [selectors] if isinstance(selectors, str) else list(selectors)
    name = label or (sels[0] if sels else "?")

    for sel in sels:
        try:
            loc_all = page.locator(sel)
            n = loc_all.count()
        except Exception:
            continue
        if n == 0:
            continue

        # 只统计「可见」的
        visible_idx = []
        for i in range(n):
            try:
                if loc_all.nth(i).is_visible():
                    visible_idx.append(i)
            except Exception:
                continue

        if not visible_idx:
            continue

        if expect_unique and len(visible_idx) > 1:
            print(f"[click*] ⚠ 选择器命中 {len(visible_idx)} 个可见元素，"
                  f"为安全起见跳过: {sel}")
            continue

        idx = visible_idx[0]
        loc = loc_all.nth(idx)
        try:
            loc.scroll_into_view_if_needed()
            human_pause(0.1, 0.3)
            loc.click(timeout=timeout or C.DEFAULT_TIMEOUT)
            print(f"[click*] ✓ {name}  (选择器={sel}"
                  f"{'' if len(visible_idx) == 1 else f', 第{idx}个'})")
            human_pause()
            return True
        except PWTimeout:
            try:
                loc.evaluate("el => el.click()")
                print(f"[click*] ✓ {name} (js 降级)")
                return True
            except Exception as e:
                print(f"[click*] ✗ {name} 点击失败: {e}")
                continue
        except Exception as e:
            print(f"[click*] ✗ {name} 异常: {e}")
            continue

    print(f"[click*] ✗ 未能安全点击: {name}")
    for sel in sels:
        try:
            print(f"         候选 {sel!r} 命中 {page.locator(sel).count()} 个")
        except Exception:
            pass
    if shot_on_fail:
        p = C.SHOTS / f"fail-strict-{int(time.time())}.png"
        page.screenshot(path=str(p), full_page=True)
        print(f"[click*] 已截图 {p}")
    return False


def fill(page: Page, selectors: Sequence[str], text: str, *,
         chars_delay: tuple[int, int] = (40, 140), label: str = "") -> bool:
    """输入文本，逐字符随机延迟。"""
    sels = [selectors] if isinstance(selectors, str) else list(selectors)
    name = label or sels[0]
    loc = pick(page, sels)
    if loc is None:
        print(f"[fill] ✗ 找不到输入框: {name}  候选={sels}")
        return False
    try:
        loc.scroll_into_view_if_needed()
        loc.click()
        loc.fill("")
        for ch in text:
            loc.type(ch, delay=random.randint(*chars_delay))
        print(f"[fill] ✓ {name} = {text if len(text) < 20 else text[:20] + '…'}")
        human_pause()
        return True
    except Exception as e:
        print(f"[fill] ✗ {name} 失败: {e}")
        return False


def wait_text(page: Page, text: str, timeout: int | None = None) -> bool:
    """等页面上出现某段文字。"""
    t = timeout or C.DEFAULT_TIMEOUT
    try:
        page.locator(f"text={text}").first.wait_for(state="visible", timeout=t)
        print(f"[wait] ✓ 出现文字: {text}")
        return True
    except Exception:
        print(f"[wait] ✗ 未出现文字: {text} ({t}ms)")
        return False


def wait_url(page: Page, keyword: str, timeout: int | None = None) -> bool:
    """等 URL 包含关键词。"""
    t = timeout or C.NAV_TIMEOUT
    try:
        page.wait_for_url(f"**{keyword}**", timeout=t)
        print(f"[wait] ✓ URL 命中: {keyword}")
        return True
    except Exception:
        print(f"[wait] ✗ URL 未命中: {keyword}（当前 {page.url}）")
        return False


def text_of(page: Page, selectors: Sequence[str]) -> str | None:
    """取第一个命中元素的文本。"""
    loc = pick(page, selectors, timeout=3000)
    return loc.inner_text(timeout=600).strip() if loc else None

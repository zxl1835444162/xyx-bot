"""关活动弹窗（挡住页面会导致后续点击被拦）。

本文件由原巨型模块拆分而来（Phase C2/C1），拆分时按 AST 依赖做了拓扑排序，
每个模块只 import 排在自己前面的模块，不存在循环引用。
"""

from __future__ import annotations

from xyxbot.waiting import wait_gone, wait_until, wait_visible
from playwright.sync_api import Page

__all__ = ["_activity_modal_still_there", "_close_one_activity_modal", "close_activity_modal"]


def _close_one_activity_modal(page: Page, modal, verbose: bool) -> bool:
    """对**一个已确认可见**的活动弹窗尝试三种关法，返回是否关掉了。

    a) 优先精确的 close 按钮
    b) 「不再弹出」这类文字按钮
    c) 兜底 ESC
    每种都带条件等待（等弹窗真的消失），不再固定 sleep。
    """
    closed = False

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
                # ★ 条件等待：等这个弹窗真的消失（原来固定 sleep 0.7s）
                wait_gone(lambda m=modal: bool(m.count())
                          and m.is_visible(timeout=60),
                          timeout=1.5, interval=0.05, desc="活动弹窗关闭")
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
                    wait_gone(lambda m=modal: bool(m.count())
                              and m.is_visible(timeout=60),
                              timeout=1.5, interval=0.05, desc="活动弹窗关闭")
                    break
            except Exception:
                continue

    # c) 兜底：ESC
    if not closed:
        try:
            page.keyboard.press("Escape")
            wait_gone(lambda m=modal: bool(m.count())
                      and m.is_visible(timeout=60),
                      timeout=1.5, interval=0.05, desc="活动弹窗关闭(ESC)")
            closed = True
            if verbose:
                print("[books]   已按 ESC 关闭")
        except Exception:
            pass

    return closed



def _activity_modal_still_there(page: Page, marks, not_create: str) -> bool:
    """最终确认：活动弹窗还在不在。"""
    for mark in marks:
        try:
            if page.locator(f".n-modal{mark}{not_create}").first.is_visible(
                    timeout=400):
                return True
        except Exception:
            continue
    return False



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
            # ★ 效率改造（2026-10-05）：把存在性探测的 timeout 从 600ms 降到
            #   200ms。5 个 mark 顺序探测时，只有「真存在」的那个才需要等；
            #   不存在时每个省 400ms（最坏省 2s）。实测活动弹窗几乎不出现。
            if not modal.is_visible(timeout=200):
                continue
        except Exception:
            continue

        if verbose:
            print(f"[books] 发现活动弹窗 {mark}，尝试关闭 ...")

        closed = _close_one_activity_modal(page, modal, verbose)

        if closed:
            break

    # 最终确认：活动弹窗还在不在
    if closed:
        still = _activity_modal_still_there(page, activity_marks, not_create)
        if verbose:
            print("[books] 活动弹窗" + ("⚠ 仍然存在" if still else "✓ 已清除"))
        return not still

    return closed

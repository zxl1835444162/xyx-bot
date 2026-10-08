"""替换落盘：点「替换 / 插入」（含 JS 降级）与二次确认框。

本文件由原巨型模块拆分而来（Phase C2/C1），拆分时按 AST 依赖做了拓扑排序，
每个模块只 import 排在自己前面的模块，不存在循环引用。
"""

from __future__ import annotations

from playwright.sync_api import Page
from xyxbot.ai.body import get_body_text
from xyxbot.ai.elements import CLICK_FAST_TIMEOUT, _fill_first, _safe_click, _shot, cancel_requested, dismiss_dialogs
from xyxbot.ai.selectors import AI_SELECTORS, ANCHOR_TEXT, REVIEW_CARD_ALT, REVIEW_CARD_SEL, REVIEW_PANE_SEL, REVIEW_SEP
from xyxbot.waiting import wait_gone, wait_until, wait_visible
import time

__all__ = ["_click_replace_button", "_js_click_replace_button", "dismiss_review_confirm", "replace_review_result"]



def _click_replace_button(page: Page) -> bool:
    """① 点「替换 / 插入」：优先用「类名 + 位置」精确点（比文字更稳）。

    ★ 不先 scroll_into_view_if_needed（它可能 15s 超时直接失败），直接 click；
      短超时失败后依次 JS / force 降级（残留遮罩会拦原生点击，长超时只会白等，
      详见 CLICK_FAST_TIMEOUT）。
    """
    clicked = False
    for sel in AI_SELECTORS["btn_review_replace"]:
        try:
            loc = page.locator(sel)
            n = loc.count()
            if not n:
                continue
            btn = loc.last
            try:
                btn.click(timeout=CLICK_FAST_TIMEOUT)
            except Exception:
                try:
                    btn.evaluate("e => e.click()")
                except Exception:
                    btn.click(timeout=CLICK_FAST_TIMEOUT, force=True)
            clicked = True
            print(f"[ai] ✓ 点击「替换 / 插入」（{sel[:52]}…）")
            break
        except Exception as e:
            print(f"[ai] ⚠ 常规点击失败：{str(e).splitlines()[0]}")
            continue
    return clicked



def _js_click_replace_button(page: Page) -> bool:
    """② JS 降级：按类名找 success 型按钮直接 click()（文字匹配兜底）。"""
    clicked = False
    try:
        clicked = bool(page.evaluate("""() => {
          // 优先 footer 里的 success 型
          const cards = document.querySelectorAll(
              '.chapter-right-workspace .n-card.chapter-side-pane-c, '
              + '.n-card.chapter-side-pane-card');
          for (const c of cards) {
            const footer = c.querySelector('.n-card__footer') || c;
            const b = [...footer.querySelectorAll(
                'button.n-button--success-type')]
                .filter(x => x.offsetParent !== null);
            if (b.length) {
              b[b.length - 1].scrollIntoView({block:'center'});
              b[b.length - 1].click();
              return true;
            }
          }
          // 兜底：文字匹配（去空格）
          const all = [...document.querySelectorAll('button')]
            .filter(b => b.offsetParent !== null
                && (b.innerText||'').replace(/\\s/g,'').includes('替换'));
          if (all.length) { all[all.length-1].click(); return true; }
          return false;
        }"""))
        if clicked:
            print("[ai] ✓ JS 降级点击「替换 / 插入」")
    except Exception as e:
        print(f"[ai] ⚠ JS 降级失败：{str(e).splitlines()[0]}")
    return clicked



def replace_review_result(page: Page, wait: float = 1.0) -> bool:
    """点「替换 / 插入」，把审稿结果**落到正文**。

    ★ 这是审稿流程的**最后一步**（用户明确要求）：
        生成完 → 结果区出现【替换 / 插入】→ 点它 → 结果替换进正文。
    ★ 实测 DOM（2026-10-03）：
        button 文字 = "替换 / 插入"
        class      = n-button n-button--success-type n-button--small-type
        位置        = .n-card__footer（审稿抽屉底部）
    ★ 关弹窗原则：若出现二次确认框，**有则点确认、没有就跳过**，绝不阻塞。

    Returns:
        bool 是否点到「替换 / 插入」
    """
    print("[ai] --- 点「替换 / 插入」（落盘到正文）---")

    # ① 点击（类名+位置精确点 → 失败走 ② JS 降级）
    clicked = _click_replace_button(page)
    if not clicked:
        clicked = _js_click_replace_button(page)

    if not clicked:
        print("[ai] ✗ 找不到「替换 / 插入」按钮")
        _shot(page, "ai_review_replace_failed")
        return False

    # ★ 效率改造：原来是固定 `sleep(wait=1.2)` 等替换落盘。
    #   替换是前端本地操作，通常几十毫秒就完成；这里改为**等正文真的变了**
    #   （与替换前对比字数/内容），一变就继续，最慢不超过 wait。
    try:
        body_before = get_body_text(page)
        wait_until(lambda: get_body_text(page) != body_before,
                   timeout=max(wait, 1.0), interval=0.08, desc="替换落盘")
    except Exception:
        time.sleep(min(wait, 0.5))      # 读不到正文时保守等一点

    # ③ 可能的二次确认框（有则点、没则跳过，绝不阻塞）
    try:
        n = dismiss_review_confirm(page)
        if n:
            print(f"[ai] 处理了 {n} 个替换确认框")
            # 确认框消失即可继续（原来固定 sleep 1.2s）
            wait_gone(lambda: any(
                page.locator(s).first.is_visible(timeout=60)
                for s in AI_SELECTORS["review_replace_confirm"]
                if page.locator(s).count()),
                timeout=2.0, desc="确认框关闭")
    except Exception:
        pass

    return True




def dismiss_review_confirm(page: Page, verbose: bool = True) -> int:
    """关掉「替换」可能弹出的二次确认框。

    ★ 原则（用户要求）：**有则关、没有就跳过**，绝不影响进程。
      返回点掉的个数（0 = 本来就没有）。
    """
    closed = 0
    for sel in AI_SELECTORS["review_replace_confirm"]:
        try:
            loc = page.locator(sel).first
            if loc.count() and loc.is_visible():
                _safe_click(loc, label="替换确认框")
                closed += 1
                if verbose:
                    print(f"[ai]   ✓ 点确认：{sel[:44]}")
                break
        except Exception:
            continue
    return closed

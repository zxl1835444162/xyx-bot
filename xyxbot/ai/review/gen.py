"""生成与等待：点「生成」/ 是否生成中 / 结果是否就绪 / 等完成。

本文件由原巨型模块拆分而来（Phase C2/C1），拆分时按 AST 依赖做了拓扑排序，
每个模块只 import 排在自己前面的模块，不存在循环引用。
"""

from __future__ import annotations

from playwright.sync_api import Page
from xyxbot.ai.elements import CLICK_FAST_TIMEOUT, _fill_first, _safe_click, _shot, cancel_requested, dismiss_dialogs
from xyxbot.ai.selectors import AI_SELECTORS, ANCHOR_TEXT, REVIEW_CARD_ALT, REVIEW_CARD_SEL, REVIEW_PANE_SEL, REVIEW_SEP
from xyxbot.waiting import wait_gone, wait_until, wait_visible
import time

__all__ = ["review_generating", "review_result_ready", "start_review", "wait_review_done"]



def start_review(page: Page, wait: float = 0.5) -> bool:
    """点审稿卡片**底部固定栏**的「生成」按钮，开始审稿。

    ★ 踩坑（2026-10-03）：
      ① 全局 `button:has-text('生成')` → 命中左栏章节菜单浮层的
         「一键生成概要」，点错。
      ② 锁 `REVIEW_PANE_SEL`（.n-card-content）→ 找不到，因为
         **「生成」在 `.n-card__footer`，不在 `.n-card-content` 里**。
      正解：用 `REVIEW_CARD_SEL`（整个卡片），footer 就在其中。
    """
    print("[ai] --- 点「生成」（开始审稿）---")
    ok = False

    # ① 常规点击（卡片范围内，优先 footer）
    for sel in AI_SELECTORS["btn_review_start"]:
        try:
            loc = page.locator(sel)
            n = loc.count()
            if n:
                # ★ 短超时原生点击 + JS 降级（残留遮罩会拦原生点击，
                #   否则这里要白等满 5 秒；详见 CLICK_FAST_TIMEOUT 说明）
                try:
                    loc.last.click(timeout=CLICK_FAST_TIMEOUT)
                except Exception:
                    loc.last.evaluate("e => e.click()")
                ok = True
                print(f"[ai] ✓ 点击「生成」（{sel[:48]}…）")
                break
        except Exception as e:
            print(f"[ai] ⚠ 常规点击失败：{str(e).splitlines()[0]}")
            continue

    # ② JS 降级：沿「待审文本」卡片往上找到含「生成」的 footer 直接点
    if not ok:
        try:
            ok = bool(page.evaluate("""(anchor) => {
              const content = [...document.querySelectorAll('.n-card-content')]
                  .find(c => c.innerText.includes(anchor));
              if (!content) return false;
              const card = content.closest('.n-card');
              if (!card) return false;
              const btns = [...card.querySelectorAll('button')]
                  .filter(b => b.innerText.trim() === '生成');
              if (!btns.length) return false;
              btns[btns.length - 1].click();
              return true;
            }""", ANCHOR_TEXT))
            if ok:
                print("[ai] ✓ JS 降级点击（卡片 footer 内的生成）")
        except Exception as e2:
            print(f"[ai] ✗ JS 降级也失败：{str(e2).splitlines()[0]}")

    if not ok:
        _shot(page, "ai_review_start_failed")
        return False

    # ★ 效率改造（2026-10-04 实测）：原来是「点完固定 sleep(wait=0.5)」。
    #   改成条件等待「审稿真的开始」（出现生成中状态）；超时 =
    #   max(wait,0.5)+2.0（比原来更宽容），所以最坏情况不比旧实现差。
    #   ★ 这个等待**不参与成败判定**：ok 已由点击结果决定。
    started = wait_until(lambda: review_generating(page),
                         timeout=max(float(wait), 0.5) + 2.0,
                         interval=0.06, desc="审稿已开始")
    if started.ok:
        print(f"[ai] ✓ 已触发生成（{started.elapsed:.2f}s）")
    else:
        print("[ai] ✓ 已触发生成（未观测到生成中状态，继续）")
    return True




def review_generating(page: Page) -> bool:
    """审稿是否仍在生成中。

    ★ 判据（实测）：
        - 底部出现「停止生成」/ loading 按钮 → 生成中
        - 结果区出现「替换 / 插入」→ 已完成
        - 「深度思考中」toast 也在 → 生成中
    """
    try:
        # ① 结果区已经出现 → 肯定不是「生成中」
        if review_result_ready(page):
            return False
        # ② 「停止生成」按钮
        if page.locator("button:has-text('停止生成')").count():
            return True
        # ③ loading 型按钮
        if page.locator("button.n-button--loading").count():
            return True
        # ④ 「思考中」文案
        return bool(page.locator("text=思考中").count())
    except Exception:
        return False




def review_result_ready(page: Page) -> bool:
    """审稿结果是否已就绪（★ 权威判据：「替换 / 插入」按钮出现）。

    ★ 实测（2026-10-03 真机）：
        生成中 → 抽屉底部只有「生成」（disabled），**没有** success 型按钮
        完成后 → footer 出现一排：
                 【重新生成】【复制】【对比】【导出至作品】
                 **【替换 / 插入】**（n-button--success-type）
      所以「替换 / 插入」按钮出现 = 审稿完成，可以落盘。

    ★★ 踩坑（务必记住）：**不要用「全页文字含『替换』」做判据！**
      页面上别处（通知、其他卡片、隐藏元素）也可能带这俩字，
      会导致刚点完生成就误判「已完成（耗时 0s）」。
      必须**限定在审稿卡片的 footer 内 + 限定 success 型 class**。
    """
    try:
        # ★ 唯一硬判据：审稿卡片 footer 里的 success 型按钮
        for card_sel in (REVIEW_CARD_SEL, REVIEW_CARD_ALT):
            try:
                loc = page.locator(
                    f"{card_sel} .n-card__footer "
                    f"button.n-button--success-type")
                if loc.count() and loc.first.is_visible():
                    return True
            except Exception:
                continue
            try:
                loc = page.locator(f"{card_sel} button.n-button--success-type")
                if loc.count() and loc.first.is_visible():
                    return True
            except Exception:
                continue
        # 兜底：JS 里同样**限定在卡片 footer + success class**
        return bool(page.evaluate("""() => {
          const cards = document.querySelectorAll(
              '.chapter-right-workspace .n-card.chapter-side-pane-c, '
              + '.n-card.chapter-side-pane-card');
          for (const c of cards) {
            const footer = c.querySelector('.n-card__footer');
            if (!footer) continue;
            const ok = [...footer.querySelectorAll(
                'button.n-button--success-type')]
                .some(b => b.offsetParent !== null);
            if (ok) return true;
          }
          return false;
        }"""))
    except Exception:
        return False




def wait_review_done(page: Page, timeout: float = 600.0,
                     poll: float = 0.4,
                     confirm_hits: int = 2,
                     confirm_gap: float = 0.15) -> bool:
    """等审稿生成完成（等「替换 / 插入」按钮出现）。

    ★ 用户要求：审稿要跑几分钟很正常，所以要**耐心等满 timeout**，
      不要因为「字数稳定」之类的弱判据提前跳出。
      判据只有一条硬的：结果按钮栏出现。

    ★ 效率改造（本轮）：原来 `poll=1.5` 且「连续 2 次命中」——两次命中之间
      要等 1.5 秒，也就是**判定完成本身就固定慢 1.5 秒**；再加上粗轮询的
      期望延迟，每章在这个环节白等约 2 秒以上。

      现在拆开两个参数：
        * `poll=0.4`      —— 未完成时的轮询间隔（问得勤，但只是廉价查询）；
        * `confirm_gap=0.15` —— **两次确认命中之间的间隔**（防瞬时误判用，
          不需要 1.5 秒那么久；动画残影在 150ms 内就能分辨）。

    Args:
        timeout:      最长等多久（默认 600s = 10 分钟）
        poll:         轮询间隔
        confirm_hits: 连续命中几次才算完成（默认 2，防瞬时误判）
        confirm_gap:  两次确认之间的间隔（秒）

    Returns:
        bool 是否等到完成
    """
    print(f"[ai] --- 等审稿完成（最多 {timeout:.0f}s）---")
    t0 = time.time()
    last_beat = [0.0]
    # ★ "连续 confirm_hits 次命中"的状态机。
    #   把它写成**谓词内部状态**，就能复用 `wait_until` —— 从而白拿
    #   中止支持（用户点停止时不必等满 600 秒）与统一的心跳/超时语义。
    #   两次命中之间仍要求间隔 ≥ confirm_gap（防动画残影误判）。
    st = {"hits": 0, "last": 0.0}

    def _ready() -> bool:
        now = time.time()
        if review_result_ready(page):
            if st["hits"] == 0 or (now - st["last"]) >= confirm_gap:
                st["hits"] += 1
                st["last"] = now
            return st["hits"] >= confirm_hits
        st["hits"] = 0
        return False

    def _tick(_n):
        el = time.time() - t0
        if el - last_beat[0] >= 30:      # 每 ~30s 打一次心跳
            last_beat[0] = el
            print(f"[ai]   审稿生成中 … {el:.0f}s")

    res = wait_until(_ready, timeout=timeout, interval=poll,
                     on_poll=_tick, desc="审稿完成",
                     should_abort=cancel_requested)
    if res.aborted:
        print("[ai] ⏹ 审稿等待被中止（用户停止）")
        return False
    if res.ok:
        print(f"[ai] ✓ 审稿已完成（耗时 {res.elapsed:.0f}s）")
        return True
    print(f"[ai] ✗ 等审稿超时（{timeout:.0f}s）")
    _shot(page, "ai_review_timeout")
    return False

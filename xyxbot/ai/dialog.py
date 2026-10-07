"""续写弹窗与「残留结果页」的处理。

本文件由 `xyxbot/ai.py` 拆分而来（Phase C1）。拆分时按 AST 依赖做了拓扑排序，
所以每个模块只 import 排在自己前面的模块，不存在循环引用。
"""

from __future__ import annotations

from xyxbot.waiting import wait_gone, wait_until, wait_visible
from playwright.sync_api import Page
import time

from xyxbot.ai.elements import _click_first, _safe_click, _shot, _visible, dismiss_dialogs
from xyxbot.ai.selectors import AI_SELECTORS

__all__ = ["_close_any_continue_dialog", "_close_stale_result", "_fake_continue_dialog_present", "_has_start_button", "_stale_result_present", "close_continue_dialog", "continue_dialog_open", "open_continue_dialog"]



# ---------------------------------------------------------------- 流程步骤

def _stale_result_present(page: Page) -> bool:
    """★ 弹窗里是否残留着**上一轮的结果页**。

    判据：**任一** modal 里同时有「重新生成」和「采纳使用」按钮
    （这正是 `gen_finished` 的完成标志）。

    ★★ 修正（2026-10-05）：原来只看 `.n-modal.first`。但续写弹窗未必是
      页面上**第一个** modal —— 审稿抽屉、模型选择弹窗等都是 `.n-modal`，
      若它们排在前面，就会**检查错对象**（把非续写弹窗当结果页/反之），
      导致残留检测失效 —— 这正是「下一章必报错」的可能成因。
      改为**遍历所有 modal**，任一命中即算残留。

    ★★ 为什么必须单独判这个（2026-10-04 用户报障）：
      批量跑章时，每章开头会点「AI续写正文」开新弹窗。但**如果上一章的
      结果弹窗没被关干净**，`open_continue_dialog` 那句
      「弹窗存在就算成功」会**直接把旧结果页当成新弹窗收下**。
      后果链条：
        开弹窗「成功」→ 填剧情/选模型其实作用在旧页面上 →
        `start_generate` 点到的可能不是「开始AI续写」→
        `wait_generation` 一上来就看到「重新生成」按钮 → **立刻判"已完成"**
        → `get_gen_word_count` 读到**上一轮的旧字数**。

      用户日志里的铁证：第37章与第38章耗时仅 **16s / 19s**（正常需 3~5 分钟），
      且字数为**完全相同**的 **2744**。这不是"生成快"，是**读到了残留值**。
    """
    try:
        modals = page.locator(".n-modal")
        n = modals.count()
        for i in range(min(n, 6)):
            m = modals.nth(i)
            try:
                if not m.is_visible():
                    continue
                has_regen = bool(m.locator("button:has-text('重新生成')").count())
                has_accept = bool(m.locator("button:has-text('采纳使用')").count())
                if has_regen and has_accept:
                    return True
            except Exception:
                continue
        return False
    except Exception:
        return False



def _close_stale_result(page: Page) -> bool:
    """关掉残留的结果弹窗，给新弹窗让路。

    优先点右上角关闭 / 取消；都没有就按 ESC。

    ★★ 修正（2026-10-05）：原来只操作 `.n-modal.first`，可能关错弹窗
      （页面上其它 modal 排在前）。现在**优先定位含「采纳使用」的那个 modal**，
      只关它；找不到才退回第一个 modal。

    Returns: 是否执行了关闭动作
    """
    print("[ai] ⚠ 发现上一轮的结果页还开着 → 先关掉，避免读到旧字数")
    closed = False
    target = None
    try:
        modals = page.locator(".n-modal")
        n = modals.count()
        for i in range(min(n, 6)):
            m = modals.nth(i)
            try:
                if not m.is_visible():
                    continue
                if m.locator("button:has-text('采纳使用')").count():
                    target = m
                    break
            except Exception:
                continue
        if target is None and n:
            target = modals.first
    except Exception:
        target = None

    if target is not None:
        for sel in ("button[aria-label='close']", ".n-base-close",
                    "button:has-text('取消')", "button:has-text('关闭')"):
            try:
                b = target.locator(sel).first
                if b.count() and b.is_visible(timeout=300):
                    b.click(timeout=2000)
                    closed = True
                    print(f"[ai]   ✓ 已点关闭({sel})")
                    break
            except Exception:
                continue
    if not closed:
        try:
            page.keyboard.press("Escape")
            closed = True
            print("[ai]   ✓ 已按 ESC 关闭")
        except Exception:
            pass
    # 等它真的消失（最多 3s）
    wait_gone(lambda: _stale_result_present(page), timeout=3.0,
              interval=0.1, desc="残留结果页关闭")
    return closed



def _has_start_button(page: Page) -> bool:
    """当前页面上是否**可见**「开始 AI 续写」按钮（续写弹窗可用的权威标志）。

    ★ 2026-10-05 新增。用户实测日志里第2章就是栽在这：
      弹窗"出现了"（含「续写正文」字样），但里面**没有**这个按钮
      ⇒ `start_generate` 找不到目标 ⇒ 整章失败，而 reason 还被显示成
        「2028 字达标，已采纳」（误导）。
    """
    for sel in AI_SELECTORS["btn_start"]:
        try:
            loc = page.locator(sel)
            n = loc.count()
            for i in range(min(n, 4)):
                try:
                    if loc.nth(i).is_visible():
                        return True
                except Exception:
                    continue
        except Exception:
            continue
    return False



def _fake_continue_dialog_present(page: Page) -> bool:
    """是否存在**假的**续写弹窗：有「续写正文」字样、但没有「开始 AI 续写」按钮。

    这正是用户第2章失败时的状态。
    """
    if _has_start_button(page):
        return False
    try:
        loc, _sel = _visible(page, AI_SELECTORS["dialog"], timeout=300)
        return loc is not None
    except Exception:
        return False



def _close_any_continue_dialog(page: Page) -> bool:
    """关掉当前的续写弹窗（不论真假），容忍关不掉。

    ★ 与 `_close_stale_result` 的区别：那个针对「完成态结果页」，
      这个针对「任何续写弹窗」（含没有开始按钮的假弹窗）。
    """
    closed = False
    for sel in ("button[aria-label='close']", ".n-base-close",
                "button:has-text('取消')", "button:has-text('关闭')"):
        try:
            loc = page.locator(f".n-modal {sel}")
            n = loc.count()
            for i in range(min(n, 4)):
                b = loc.nth(i)
                try:
                    if b.is_visible():
                        b.click(timeout=2000)
                        closed = True
                        print(f"[ai]   ✓ 已点关闭({sel})")
                        break
                except Exception:
                    continue
            if closed:
                break
        except Exception:
            continue
    if not closed:
        try:
            page.keyboard.press("Escape")
            closed = True
            print("[ai]   ✓ 已按 ESC 关闭假弹窗")
        except Exception:
            pass
    wait_gone(lambda: _fake_continue_dialog_present(page), timeout=2.5,
              interval=0.1, desc="假续写弹窗关闭")
    return closed



def open_continue_dialog(page: Page, wait: float = 3.0) -> bool:
    """点顶部「AI续写正文」，等弹窗出现。

    ★ 实测坑：打开作品后常有干扰弹窗（「是否默认打开上次章节？」
      「国庆特惠」通知）挡住工具栏，导致点击超时。所以：
      先清干扰 → 点击 → 没弹窗就再清一次重试。

    ★★ 效率改造（2026-10-04 实测）：
       原实现是「点完固定 `sleep(wait=3.0)` → 再检查一次」。
       实测弹窗出现只需 ~300ms（整函数据 3387ms，其中 3000ms 是白等），
       而且**只检查一次**：慢一点就误判失败、白做一轮重试。
       现在改成条件等待，超时反而**更宽容**（`max(wait,3)+2` 秒），
       所以"弹窗慢"的最坏情况不会比旧实现差。

    ★★★ 正确性加固（2026-10-04，用户报「16 秒生成完 / 两章字数一模一样」）：
       进入本函数时先 `_close_stale_result()` —— 若上一轮结果页还开着，
       必须先关掉。否则「弹窗存在」这个判据会把**旧结果页**当新弹窗收下，
       导致后续读到**旧字数**（详见 `_stale_result_present` 的说明）。
    """
    print("[ai] --- 打开「AI续写正文」弹窗 ---")

    # ★ 先清掉可能残留的上一轮结果页（否则会被误当成新弹窗）
    if _stale_result_present(page):
        _close_stale_result(page)

    # ★★ 2026-10-05（用户实测日志定位）：若已有一个**假弹窗**（含"续写正文"
    #   字样、但没有「开始 AI 续写」按钮），先关掉它，否则下面 `_dialog_shown`
    #   会把它当成"弹窗已出现"，后面 start_generate 必然找不到按钮。
    #   ★ 用户日志铁证（第2章）：
    #       ✓ 弹窗已出现: .n-modal:has-text('续写正文')
    #       ✓ 续写弹窗为初始态（干净的新弹窗）
    #       ...
    #       ✗ 找不到目标: 开始 AI 续写     ← 就是这个假弹窗害的
    if _fake_continue_dialog_present(page):
        print("[ai] ⚠ 发现一个不含「开始 AI 续写」的假弹窗（残页）→ 先关掉")
        _close_any_continue_dialog(page)

    # 清干扰弹窗
    n = dismiss_dialogs(page, verbose=True)
    if n:
        print(f"[ai] 清掉了 {n} 个干扰弹窗")

    def _dialog_shown() -> bool:
        # ★★ 判据升级（2026-10-05）：必须**真的能看到「开始 AI 续写」按钮**，
        #   才算"可用的续写弹窗"。只凭 `:has-text('续写正文')` 会把残页收下。
        loc, sel = _visible(page, AI_SELECTORS["dialog"], timeout=2500)
        if loc is None:
            return False
        # 弹窗在 → 再确认里面有开始按钮
        if _has_start_button(page):
            print(f"[ai] ✓ 弹窗已出现且含「开始 AI 续写」: {sel}")
            return True
        print(f"[ai] ⚠ 弹窗出现但未见「开始 AI 续写」按钮（疑似残页）: {sel}")
        return False

    _click_first(page, AI_SELECTORS["btn_continue"], label="AI续写正文")
    if wait_until(_dialog_shown, timeout=max(float(wait), 3.0) + 2.0,
                  interval=0.08, desc="续写弹窗出现").ok:
        return True

    # 没出来 → 再清一次干扰，重试点击
    print("[ai] 弹窗未出现，清理干扰后重试 …")
    dismiss_dialogs(page, verbose=True)
    page.keyboard.press("Escape")
    # ★ 等遮罩/ESC 生效，而不是固定 sleep 0.6s
    wait_gone(lambda: page.locator(".n-modal-mask").first
              .is_visible(timeout=60), timeout=1.5, interval=0.05,
              desc="干扰遮罩消失")

    _click_first(page, AI_SELECTORS["btn_continue"], label="AI续写正文(重试)")
    if wait_until(_dialog_shown, timeout=float(wait) + 3.5,
                  interval=0.08, desc="续写弹窗出现(重试)").ok:
        return True

    print("[ai] ✗ 续写弹窗未出现")
    _shot(page, "ai_dialog_missing")
    return False



# ================================================================ ★ 续写 → 审稿 串联
#
#   用户需求（2026-10-03）：
#     「一章的生成已经完成了，我有些担心**生成完之后、与审稿开始之间的状态**，
#       请你从 0 开始走一遍流程，让字数限制宽一点，避免重试；
#       另外你接了吗？就是，**生成完之后，接着审稿**」
#
#   ★ 为什么单独写这个函数：
#     续写（弹窗）和审稿（右侧抽屉）是**两套完全不同的界面**，
#     衔接处有 3 个坑：
#
#     坑1.「采纳使用」点了之后，**续写弹窗不会自动关**。
#          弹窗是居中模态，会**截获点击** → 直接点「AI审稿」必然超时。
#          必须先 `close_continue_dialog()` 把弹窗关掉。
#
#     坑2. 采纳后正文写入需要一点时间（编辑器里要渲染出来），
#          立刻开审稿可能读到空正文 / 旧正文。
#          必须 `wait_body_change()` 等字数真的变了。
#
#     坑3. 审稿抽屉打开后，页面布局变了，但正文还在编辑器里，
#          所以审稿的「待审文本」会自动带上刚生成的正文 —— 这是我们要的。
# ================================================================


def continue_dialog_open(page: Page) -> bool:
    """续写弹窗是否还开着（★ 以「采纳使用 / 重新生成」按钮为准）。

    ★ 实测：采纳之后弹窗可能**仍在**（不自动关），
      它是居中模态，会拦掉后续所有点击。
    """
    for sel in AI_SELECTORS["btn_accept"] + AI_SELECTORS["btn_regen"]:
        try:
            loc = page.locator(sel)
            for i in range(min(loc.count(), 4)):
                if loc.nth(i).is_visible():
                    return True
        except Exception:
            continue
    return False



def close_continue_dialog(page: Page, wait: float = 1.5,
                          max_try: int = 4) -> bool:
    """★ 关掉续写弹窗（用于「续写完成后要接着审稿」的衔接）。

    ★ 关弹窗原则（用户要求）：**有则关、没有就跳过**，绝不影响主进程。

    关法按顺序试：
        ① 弹窗右上角的 × / 关闭按钮
        ② ESC
        ③ 点遮罩空白处（Naive UI 点 mask 可关）
    每次关完都复查，关掉了就返回。

    Returns:
        bool 是否已关掉（本来就关着 → 也算 True）
    """
    if not continue_dialog_open(page):
        print("[ai] 续写弹窗已关闭，无需处理")
        return True

    print("[ai] --- 关闭续写弹窗（衔接审稿）---")

    def _wait_closed(timeout: float = 2.5) -> bool:
        """★ 条件等待弹窗真的关掉（替代原来的固定 sleep 0.6/0.8）。

        原来每次关完都 `sleep(0.8)` 再查一次 —— 弹窗往往几十毫秒就没了，
        这一秒是白等的。而且固定等待后只查一次，没关掉就要等下一轮重试。
        """
        return wait_gone(lambda: continue_dialog_open(page),
                         timeout=timeout, interval=0.04).ok

    for attempt in range(1, max_try + 1):
        # ① 找弹窗里的关闭按钮
        #    ★ 实测（2026-10-03）：续写弹窗的 × 是
        #      `button[aria-label='close'].n-base-close.n-card-header__close`
        #      在弹窗**右上角**（约 x=1281,y=29，18x18）
        for sel in [
            "button[aria-label='close'].n-card-header__close",
            ".n-card-header .n-base-close",
            "button.n-base-close--absolute",
            ".n-modal button[aria-label='close']",
            ".n-modal .n-base-close",
        ]:
            try:
                loc = page.locator(sel)
                n = loc.count()
                for i in range(min(n, 5)):
                    b = loc.nth(i)
                    if not b.is_visible():
                        continue
                    _safe_click(b, label="关闭续写弹窗")
                    if _wait_closed():
                        print(f"[ai] ✓ 已关闭续写弹窗（点 {sel}）")
                        return True
                    break
            except Exception:
                continue

        # ② ESC
        try:
            page.keyboard.press("Escape")
            if _wait_closed(timeout=2.0):
                print("[ai] ✓ 已关闭续写弹窗（ESC）")
                return True
        except Exception:
            pass

        # ③ 点遮罩空白（弹窗左上角外侧）
        try:
            mask = page.locator(".n-modal-mask, .n-modal-container").first
            if mask.count():
                box = mask.bounding_box()
                if box:
                    page.mouse.click(box["x"] + 8, box["y"] + 8)
                    if _wait_closed():
                        print("[ai] ✓ 已关闭续写弹窗（点遮罩）")
                        return True
        except Exception:
            pass

        print(f"[ai]   第 {attempt}/{max_try} 次没关掉，重试…")
        time.sleep(0.3)

    print("[ai] ⚠ 续写弹窗未关掉（继续走，后面靠 dismiss_dialogs 兜底）")
    _shot(page, "ai_close_continue_failed")
    return False

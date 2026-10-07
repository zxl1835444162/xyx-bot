"""生成与等待（开始生成、等完成、字数、重生成、采纳）。

本文件由 `xyxbot/ai.py` 拆分而来（Phase C1）。拆分时按 AST 依赖做了拓扑排序，
所以每个模块只 import 排在自己前面的模块，不存在循环引用。
"""

from __future__ import annotations

from xyxbot.waiting import wait_gone, wait_until, wait_visible
from playwright.sync_api import Page
from typing import Callable, List, Optional
import time

from xyxbot.ai.body import get_body_text
from xyxbot.ai.current import _text_of
from xyxbot.ai.dialog import _stale_result_present, continue_dialog_open
from xyxbot.ai.elements import _click_first, _shot, cancel_requested
from xyxbot.ai.selectors import AI_SELECTORS

__all__ = ["accept_result", "gen_dialog_open", "gen_finished", "gen_in_progress", "generate_with_word_check", "get_gen_word_count", "regenerate", "start_generate", "wait_generation", "wait_result_gone"]



def start_generate(page: Page, wait: float = 2.0) -> bool:
    """点「开始 AI 续写」。

    ★ 效率改造（2026-10-04 实测）：原来是「点完固定 sleep(wait=2.0)」。
      改成本条件等待「生成真的开始」，两种情况都立刻继续：
        · 已出现「停止生成」→ 生成启动
        · 已出现「重新生成」→ 已经生成完（短内容时可能快到看不到进行态）
      超时仍用 max(wait,2)+1.5（比原来更宽容），所以最坏情况不比旧实现差。
      ★ 这个等待**不参与成败判定**：看不到启动迹象也照样返回 True，
        后面 `wait_generation` 才是真正的判据。
    """
    print("[ai] --- 开始 AI 续写 ---")
    if not _click_first(page, AI_SELECTORS["btn_start"],
                        label="开始 AI 续写", shot_on_fail=True):
        return False

    started = wait_until(lambda: gen_in_progress(page) or gen_finished(page),
                         timeout=max(float(wait), 2.0) + 1.5,
                         interval=0.06, desc="生成已启动")
    if started.ok:
        print(f"[ai] ✓ 生成已启动（{started.elapsed:.2f}s）")
    else:
        print("[ai]   （暂未看到生成的启动迹象，继续等待）")
    return True



# ---------------------------------------------------------------- 生成结果处理
#
# ★ 实测（2026-10-03）点「开始 AI 续写」后，会弹出**第二个**弹窗
#   （标题「AI 续写」，右上角显示「模型: 细腻版」），内容区是个
#   **`textarea`**，右下角显示本次生成的字数。
#
#   底部按钮栏（`.n-card__footer`）：
#       上一步 | 重新生成 | 继续追问 | 复制 | 对比 | 导出至作品 | 推送至备忘录 | 采纳使用
#
#   ★ 字数元素的坑：
#     弹窗里 `.n-input-word-count` 可能有好几个，比如续写要求输入框上有
#     `3 / 35`。**生成字数那个挂在 `textarea` 上**，路径是
#     `.n-modal .n-input--textarea .n-input-word-count`，用这个才准。
#
#   ★ 外部还有一个 `.chapter-word-count`（左侧章节字数，如 73），
#     类名不同，不会误抓。

def gen_dialog_open(page: Page) -> bool:
    """生成结果弹窗是否已出现（以「采纳使用」按钮为准）。"""
    try:
        return bool(page.locator(AI_SELECTORS["btn_accept"][0]).count())
    except Exception:
        return False



def gen_in_progress(page: Page) -> bool:
    """生成是否**正在进行中**。

    ★ 实测（2026-10-03，逐 3 秒采样全过程）：
        生成中 → 弹窗按钮栏是  [提示词] [""] [停止生成]
        完成后 → 弹窗按钮栏是  [上一步] [重新生成] [继续追问] … [采纳使用]

      所以「正在生成」的可靠标志 = 弹窗里有 **「停止生成」** 按钮，
      以及正文 textarea 的字符数**还在增长**。
    """
    try:
        modal = page.locator(".n-modal").first
        if not modal.count():
            modal = page.locator(".n-card").first
        if not modal.count():
            return False
        # ① 「停止生成」按钮在 → 正在生成
        if modal.locator("button:has-text('停止生成')").count():
            return True
        # ② 「深度思考中」这类 loading 按钮在 → 正在生成
        if modal.locator("button.n-button--loading").count():
            return True
        return False
    except Exception:
        return False



def gen_finished(page: Page) -> bool:
    """生成是否**已完成**（结果页的完整按钮栏已渲染）。

    ★ 权威判据：「重新生成」按钮出现。
      生成中完全没有这个按钮（只有「停止生成」），完成后才出现。
      这比『字数稳定』可靠得多 —— 字数稳定在生成停顿的瞬间会误判。

    ★★ 修正（2026-10-05）：原来只查 `.n-modal.first`。但页面上可能有多个
      modal（审稿抽屉、模型选择弹窗等），续写结果弹窗未必排第一。改为
      **遍历所有可见 modal**，任一含「重新生成」+「采纳使用」即算完成。
    """
    try:
        modals = page.locator(".n-modal")
        n = modals.count()
        for i in range(min(n, 6)):
            m = modals.nth(i)
            try:
                if not m.is_visible():
                    continue
                if (m.locator("button:has-text('重新生成')").count()
                        and m.locator("button:has-text('采纳使用')").count()):
                    return True
            except Exception:
                continue
        # 兜底：没有 .n-modal 时看 .n-card
        cards = page.locator(".n-card")
        cn = cards.count()
        for i in range(min(cn, 4)):
            c = cards.nth(i)
            try:
                if not c.is_visible():
                    continue
                if (c.locator("button:has-text('重新生成')").count()
                        and c.locator("button:has-text('采纳使用')").count()):
                    return True
            except Exception:
                continue
        return False
    except Exception:
        return False



def wait_generation(page: Page, timeout: float = 240.0,
                    poll: float = 0.4,
                    prev_count: int = -1) -> bool:
    """等生成完成。

    ★ 实测（2026-10-03，逐 3 秒采样）得到**可靠判据**：
        生成中 → 按钮栏 = [提示词] [""] [停止生成]，正文 textarea 字符数持续增长
        完成后 → 按钮栏 = [上一步] [重新生成] [继续追问] … [采纳使用]

      因此判据用「**「重新生成」按钮出现**」定完成、
      「**「停止生成」/loading 按钮在**」定进行中。
      ~~不再用「字数稳定」~~ —— 生成途中停顿会造成误判。

    Args:
        timeout:    最长等多久（秒）
        poll:       轮询间隔（起始值，带轻微退避）
        prev_count: 上一轮字数（仅用于日志；不参与判定）

    Returns:
        bool 是否等到完成

    ★ 效率改造（本轮）：原实现 = 开头固定 `sleep(1.5)` + `poll=2.0`
      + 完成后固定 `sleep(1.2)`，即**每章至少白等 2.7 秒**，
      且粗轮询让「真正完成」那一刻平均还要多等约 1 秒。
      现在：去掉开头 1.5s（用条件等待覆盖"结果页还没渲染"）；
      `poll` 2.0→0.4（判据只是廉价的 `count()` 查询）；
      完成后改为**等字数真的渲染出来**（最多 2s，拿不到也不阻塞）。

    ★★★ 正确性加固（2026-10-04，用户报「16 秒生成完」）：
      `gen_finished` 的判据是「『重新生成』按钮出现」。如果调用本函数时
      **旧结果页还在**（新弹窗没干净打开 / 上一轮没下架），第一次轮询就会
      **立刻返回"已完成"**，随后 `get_gen_word_count` 读到旧字数 ——
      表现为「几十秒就跑完一章」+「两章字数完全相同」。

      因此新增 **`require_started`**：必须**先观察到本轮真的在生成**
      （`gen_in_progress` 为真，或曾观察到结果页消失），才允许接受
      「已完成」的判定。若整轮都没看到启动迹象，则**拒绝采信**，
      打印明确告警并返回 False（让上层走失败路径，而不是拿旧字数当战果）。
    """
    print(f"[ai] --- 等待生成完成（最多 {int(timeout)}s）---")
    saw_busy = [False]
    last_beat = [0.0]
    _t0 = time.time()

    # ★ 进入时结果页是否已经"完成态"（用于判断这是不是残留）
    _stale_at_entry = _stale_result_present(page)
    if _stale_at_entry:
        print("[ai] ⚠ 进入等待时结果页就已经是「完成态」"
              "（可能是上一轮残留）→ 要求先观察到本轮启动才采信")
    started_ok = [False]     # 是否已确认「本轮真的启动了」

    def _tick(_n):
        if gen_in_progress(page):
            saw_busy[0] = True
            started_ok[0] = True
        el = time.time() - _t0
        if el - last_beat[0] >= 20:
            last_beat[0] = el
            state = "生成中" if gen_in_progress(page) else "等待结果页"
            print(f"[ai]   已等 {int(el)}s …（{state}）")

    def _finished_and_trustworthy() -> bool:
        """★ 「已完成」+「值得采信」两个条件都满足才算真的完成。

        值得采信 = 满足**任一**：
          a) 本轮期间观察到过生成中（`gen_in_progress`）—— 最强证据
          b) 进入时并非"完成态"（即弹窗原本是干净的，那"重新生成"出现
             只能是本轮生成出来的）
          c) 完成态出现过又消失、再出现（说明经历了"生成→完成"的完整过程）

        若进入时就已经是完成态、且整轮都没看到任何生成迹象 ⇒ **不采信**，
        继续等（后面会超时并报错），绝不会把旧字数当本轮结果。
        """
        if not gen_finished(page):
            return False
        if started_ok[0]:
            return True          # a
        if not _stale_at_entry:
            return True          # b
        return False             # 残留态且无启动证据 → 不采信

    # ★★ 必须是 lambda：`gen_finished` 需要 page 参数。
    #   直接写 `wait_until(gen_finished, ...)` 会**每轮抛 TypeError**，
    #   被 wait_until 当成"未满足"吞掉 → 等待**必然超时**。
    #   实测代价：每章干等满 300 秒才判"生成失败"，而生成其实 ~9 秒就好。
    # ★ should_abort：用户点「停止」时立刻退出，不等满 timeout。
    res = wait_until(_finished_and_trustworthy,
                     timeout=timeout, interval=poll,
                     on_poll=_tick, desc="生成完成",
                     should_abort=cancel_requested)
    if res.aborted:
        print("[ai] ⏹ 生成等待被中止（用户停止）")
        return False
    if not res.ok:
        if _stale_at_entry and not started_ok[0]:
            print("[ai] ✗ 整轮都没看到生成启动，而结果页一直是完成态"
                  " —— 判定为**残留结果页**，拒绝采信其字数")
        else:
            print(f"[ai] ✗ 等了 {int(timeout)}s 还没生成完"
                  + ("（期间有看到生成动作）" if saw_busy[0] else "（未见生成动作）"))
        _shot(page, "ai_generate_timeout")
        return False

    # ★ 等字数渲染出来（原来固定 sleep 1.2s）
    #   ★★ 诊断（2026-10-05）：把「为什么算完成」和读到的字数都打出来，
    #      方便定位「还没生成就有字数/已满足」这类报告。
    _why = ("a:期间看到生成中" if started_ok[0]
            else ("b:进入时弹窗干净" if not _stale_at_entry else "?"))
    print(f"[ai]   [diag] 判完成依据 = {_why}，进入时残留={_stale_at_entry}")
    cnt = -1
    if wait_until(lambda: get_gen_word_count(page) > 0,
                  timeout=2.0, interval=0.1, desc="字数渲染").ok:
        cnt = get_gen_word_count(page)
    extra = f"，字数 {cnt}" if cnt > 0 else ""
    print(f"[ai] ✓ 生成完成（约 {int(res.elapsed)}s{extra}）")
    return True



def wait_result_gone(page: Page, timeout: float = 12.0,
                     poll: float = 0.5) -> bool:
    """等**结果页下架**（「重新生成」按钮消失）→ 说明真的开始新一轮生成了。

    ★ 用在点完「重新生成」之后：必须先看到旧结果页消失，
      否则 wait_generation 会立刻把旧页面当成「新一轮已完成」，读到旧字数。
    """
    waited = 0.0
    while waited < timeout:
        if not gen_finished(page):
            print(f"[ai] ✓ 旧结果页已下架（{waited:.1f}s），进入新一轮")
            return True
        time.sleep(poll)
        waited += poll
    return False



def get_gen_word_count(page: Page) -> int:
    """读本次生成的字数（右下角那个数字）。

    ★ 取 `.n-modal .n-input--textarea .n-input-word-count`；
      兜底再取弹窗里**最后一个** word-count。
    Returns:
        int 字数；读不到返回 -1
    """
    # 优先：textarea 上的
    for sel in AI_SELECTORS["gen_word_count"]:
        try:
            loc = page.locator(sel)
            n = loc.count()
            if not n:
                continue
            # 取可见的、纯数字的那个（越靠后越可能是内容区）
            cands = []
            for i in range(n):
                it = loc.nth(i)
                try:
                    if not it.is_visible():
                        continue
                    txt = _text_of(it, timeout=300)
                    if not txt:
                        continue
                    # 只要纯数字（排除 "3 / 35" 这种）
                    if txt.isdigit():
                        cands.append((i, int(txt)))
                    elif "/" in txt:
                        continue
                except Exception:
                    continue
            if cands:
                # 取最后一个（内容区的在下面）
                cnt = cands[-1][1]
                return cnt
        except Exception:
            continue
    return -1



def regenerate(page: Page, wait_after: float = 2.0) -> bool:
    """点「重新生成」。

    ★ 实测（2026-10-03）：
      · 点底部「重新生成」**有时**会先弹一个「使用提示」确认框：
          「对生成结果不满意？查看视频教程…」 + [重新生成] [看教程]
        这时必须再点确认框里的「重新生成」才真的重生成。
      · **有时没有这个确认框**，点了直接就开始重生成。
      所以处理策略：点完主按钮后轮询最多 ~4s，
        有确认框 → 点它；没有（或「重新生成」按钮已消失）→ 直接过。
    """
    print("[ai] --- 点「重新生成」---")
    before = get_gen_word_count(page)

    # ① 点底部主按钮「重新生成」
    _click_first(page, AI_SELECTORS["btn_regen"],
                 label="重新生成", shot_on_fail=False)

    # ② ★ 确认框**不一定出现**（有时直接重生成）。
    #    所以轮询最多 ~4s：期间一旦发现确认框里的「重新生成」就点它。
    handled = False
    for _ in range(8):
        time.sleep(0.5)
        for sel in AI_SELECTORS["regen_confirm_btn"]:
            try:
                b = page.locator(sel).first
                if b.count() and b.is_visible():
                    b.click(timeout=3000)
                    print("[ai] ✓ 已点确认框里的「重新生成」")
                    handled = True
                    break
            except Exception:
                continue
        if handled:
            break
        # 如果「重新生成」按钮已经消失 → 说明已经进入生成态，不需要确认框
        if not gen_finished(page):
            break

    if not handled:
        # 没确认框（正常情况）——有些主题会弹「使用提示」，顺手关掉
        try:
            d = page.locator(":has-text('对生成结果不满意')").first
            if d.count() and d.is_visible():
                print("[ai] ⚠ 检测到提示框，尝试 ESC 关闭")
                page.keyboard.press("Escape")
                time.sleep(0.6)
        except Exception:
            pass

    time.sleep(wait_after)
    # ③ 复核：结果页按钮栏应当已消失（回到生成态）
    if gen_finished(page):
        print(f"[ai] ⚠ 点完「重新生成」后结果页仍在（字数 {get_gen_word_count(page)}）")
    else:
        print("[ai] ✓ 已进入新一轮生成")
    return True




def accept_result(page: Page, wait_after: float = 3.0) -> bool:
    """点「采纳使用」。

    ★ 效率改造（2026-10-04 实测）：原来是「点完固定 sleep(wait_after=3.0)」，
      每章白等 3 秒。改成条件等待「采纳已生效」，命中即走：
        · 续写弹窗已关闭（站点采纳后会关掉它），或
        · 正文已经写进编辑器
      超时仍用 max(wait_after,3)（= 旧行为上限），所以最坏情况不比以前差。
      ★ 这个等待**不参与成败判定**：`ok` 仍然只看点击结果。
    """
    print("[ai] --- 点「采纳使用」---")
    ok = _click_first(page, AI_SELECTORS["btn_accept"],
                      label="采纳使用", shot_on_fail=True)
    if not ok:
        return False

    body0 = len(get_body_text(page))

    def _accepted() -> bool:
        if not continue_dialog_open(page):
            return True
        return len(get_body_text(page)) != body0

    res = wait_until(_accepted, timeout=max(float(wait_after), 3.0),
                     interval=0.08, desc="采纳生效")
    if res.ok:
        print(f"[ai] ✓ 采纳已生效（{res.elapsed:.2f}s）")
    else:
        print(f"[ai]   （{res.elapsed:.1f}s 内没等到采纳生效，继续）")
    return True



def generate_with_word_check(page: Page,
                             min_words: int = 2100,
                             max_words: int = 2300,
                             max_retry: int = 5,
                             gen_timeout: float = 240.0,
                             accept: bool = True,
                             hard_min: int = 0,
                             best_effort: bool = True) -> dict:
    """★ 按字数自动决策：达标就「采纳使用」，不达标就「重新生成」。

    规则（用户需求）：
        生成字数在 [min_words, max_words] 之间 → 点「采纳使用」
        不够 或 超过                          → 点「重新生成」（最多 max_retry 次）
        重新生成后**回到同一套判断**，直到符合区间。
        重试用完仍未达标 → **采纳最后一次生成的结果**（不再折腾）

    ★★ 上限必须真的守住（2026-10-04 用户报障后修正）：
      原实现里 `best_effort` 的兜底分支写成「重试用完 → 采纳**最后一轮**」，
      这个兜底本身没错，**错的是当时 UI 把 `max_retry` 硬编码成了 0**
      ⇒ 等于"一轮定生死"，第一轮不管多少字都走兜底直接采纳
      ⇒ 用户 2700 字（上限 2300）甚至 1800 字（下限 2100）都被当成「完成」
      ⇒ 字数区间形同虚设。

      现在职责划分清楚：
        · 本函数：超过上限 **同样要重新生成**（和「不够」一视同仁），
          重试用完才用**最后一轮**兜底 —— 逻辑简单、可预期
        · 调用方（UI）：必须传真实的 max_retry（见 ui/pages/ai_flow.py）
        · best_effort=False 时仍然严格判失败，不点采纳

    ★ 保底（避免空转）：
      有些提示词天生写得短，字数很难够到 min_words，会一直在重生成路径上转。
      因此保留 hard_min 一层保底：
        hard_min —— 硬下限。重试用完后，若当轮 ≥ hard_min（但仍低于下限），
                    仍然采纳（0 表示不启用）。推荐设为 min_words 的 ~85%。
      ★ 注意：hard_min 只对「偏低」生效，**不会**让「偏高」被放行。

    Args:
        min_words:   字数下限（含），默认 2100
        max_words:   字数上限（含），默认 2300
        max_retry:   最多重新生成几次（0 = 不重生成，只生成一轮）
        gen_timeout: 每次生成最多等多久
        accept:      达标后是否真的点「采纳使用」（False 只报告，不点）
        hard_min:    硬下限（保底采纳），0 = 关闭
        best_effort: 重试用完仍未达标时，是否采纳**最后一次**的结果

    Returns:
        {
          "ok": bool,            # 最终是否采纳成功
          "words": int,          # 最终采纳的字数
          "tries": [int, ...],   # 每轮生成的字数（按顺序）
          "rounds": int,         # 一共生成了几轮
          "reason": str,         # 结果说明
        }
    """
    print("=" * 58)
    print("  ★ 按字数自动决策")
    print(f"    目标区间 = {min_words} ~ {max_words} 字")
    print(f"    最多重生成 = {max_retry} 次"
          + (f"（保底：≥ {hard_min} 字可采纳）" if hard_min > 0 else ""))
    print("=" * 58)

    tries: List[int] = []
    rounds = 0
    prev = -1

    def _accept_now(cnt: int, tag: str) -> dict:
        if accept:
            if accept_result(page):
                return {"ok": True, "words": cnt, "tries": tries,
                        "rounds": rounds, "reason": f"{cnt} 字{tag}，已采纳"}
            return {"ok": False, "words": cnt, "tries": tries,
                    "rounds": rounds, "reason": f"{cnt} 字{tag}，但点「采纳使用」失败"}
        return {"ok": True, "words": cnt, "tries": tries,
                "rounds": rounds, "reason": f"{cnt} 字{tag}（未点采纳）"}

    for attempt in range(max_retry + 1):
        rounds += 1
        # ① 等这轮生成完成
        if not wait_generation(page, timeout=gen_timeout, prev_count=prev):
            return {"ok": False, "words": -1, "tries": tries,
                    "rounds": rounds, "reason": "生成超时"}

        # ② 读字数
        cnt = get_gen_word_count(page)
        tries.append(cnt)
        print(f"[ai] 第 {rounds} 轮生成字数：{cnt}")
        prev = cnt

        if cnt < 0:
            return {"ok": False, "words": -1, "tries": tries,
                    "rounds": rounds, "reason": "读不到生成字数"}

        # ③ 判断：入区间 → 采纳
        if min_words <= cnt <= max_words:
            print(f"[ai] ✓ {cnt} 字在 [{min_words}, {max_words}] 内 → 采纳使用")
            return _accept_now(cnt, "达标")

        # ④ 不达标 → 重新生成
        why = "不够" if cnt < min_words else "超过"
        if attempt >= max_retry:
            # ★★ 重试已用完 —— 用**最后一次生成的结果**兜底（2026-10-04 用户明确要求）。
            #
            #   规则（简单、可预期）：
            #     · 只要还没达标，就重试（最多 max_retry 次）—— 太多、太少都重试
            #     · 重试都用完仍未达标 → **采纳最后一次**的结果，不再折腾
            #
            #   历史与教训：
            #     · 最早：只有「不够」才兜底，「超过」直接判失败 → 弹窗留着不采纳，
            #       反而拦住后续操作
            #     · 2026-10-03 改成「**多了也认**」，但当时 UI 把 max_retry 写死成 0
            #       ⇒ **第一轮无论多少字都直接采纳**，字数区间形同虚设
            #       ⇒ 用户报「2700 字竟然过了 2100-2300 的限制」
            #     · 现在：**超上限同样要重试**（上面已统一处理）；真到重试用完，
            #       才用最后一轮兜底。配合 UI 侧不再写死 0，区间才真正生效。
            if best_effort and cnt > 0:
                print(f"[ai] ⚠ {cnt} 字{why}，重试 {max_retry} 次仍未达标"
                      f" → 采纳**最后一次**的结果（{cnt} 字）")
                return _accept_now(cnt, "重试用完(取最后一轮)")
            print(f"[ai] ✗ {cnt} 字（{why}），已达最大重试次数 {max_retry}")
            return {"ok": False, "words": cnt, "tries": tries,
                    "rounds": rounds,
                    "reason": f"{cnt} 字{why}，重试 {max_retry} 次仍未达标"}
        print(f"[ai] {cnt} 字（{why}）→ 重新生成"
              f"（第 {attempt + 1}/{max_retry} 次）")
        if not regenerate(page):
            return {"ok": False, "words": cnt, "tries": tries,
                    "rounds": rounds, "reason": "点「重新生成」失败"}
        # ★ 关键：必须等**旧结果页彻底下架**（「重新生成」按钮消失）
        #   再进下一轮，否则 wait_generation 会立刻认为「已完成」并读到旧字数。
        if not wait_result_gone(page, timeout=12.0):
            print("[ai] ⚠ 未观察到结果页下架，可能站点改版（继续尝试）")
        # ★ 效率改造（2026-10-04）：原来固定 sleep(1.0)。
        #   改成等「新一轮真的启动」，超时仍为 1.0s（最坏不变，命中即走）。
        wait_until(lambda: gen_in_progress(page), timeout=1.0,
                   interval=0.05, desc="新一轮生成启动")

    return {"ok": False, "words": tries[-1] if tries else -1,
            "tries": tries, "rounds": rounds, "reason": "重试耗尽"}

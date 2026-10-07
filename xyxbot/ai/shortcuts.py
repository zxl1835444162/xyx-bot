"""快捷指令面板（打开、等加载、挑选）。

本文件由 `xyxbot/ai.py` 拆分而来（Phase C1）。拆分时按 AST 依赖做了拓扑排序，
所以每个模块只 import 排在自己前面的模块，不存在循环引用。
"""

from __future__ import annotations

from xyxbot.waiting import wait_gone, wait_until, wait_visible
from playwright.sync_api import Page
import time

from xyxbot.ai.current import _text_of, current_review_requirement, current_shortcut
from xyxbot.ai.elements import CLICK_FAST_TIMEOUT, _safe_click, _shot
from xyxbot.ai.selectors import AI_SELECTORS

__all__ = ["close_shortcut_panel", "open_shortcut_panel", "pick_shortcut", "wait_shortcut_loaded"]



def open_shortcut_panel(page: Page) -> bool:
    """点「快捷选项」那一行，打开提示词选择面板。"""
    loc = page.locator(AI_SELECTORS["shortcut_row"][0]).first
    if not loc.count():
        loc = page.locator(AI_SELECTORS["shortcut_row"][1]).first
    if not loc.count():
        print("[ai] ✗ 找不到「快捷选项」那一行")
        _shot(page, "ai_shortcut_row_missing")
        return False
    try:
        loc.scroll_into_view_if_needed(timeout=CLICK_FAST_TIMEOUT)
    except Exception:
        pass
    # ★ 效率改造（2026-10-04）：删掉原来的固定 sleep(0.4)。
    #   如果确实还需要等渲染，下面的「等面板出现」会兜住（条件等待）。
    try:
        loc.click(timeout=CLICK_FAST_TIMEOUT)
    except Exception as e:
        print(f"[ai] ⚠ 常规点击失败：{str(e).splitlines()[0]}，改用 JS/force")
        try:
            loc.evaluate("e => e.click()")
        except Exception:
            try:
                loc.click(force=True, timeout=CLICK_FAST_TIMEOUT)
            except Exception as e2:
                print(f"[ai] ✗ 点不开快捷选项面板：{str(e2).splitlines()[0]}")
            _shot(page, "ai_shortcut_open_failed")
            return False

    # 等面板出现
    # ★ 效率改造：原来是 `12 × sleep(0.35)`（最多 4.2s，且每 0.35s 才查一次）。
    #   改成高频条件等待 —— 面板一出现就返回。
    if wait_visible(page, [".shortcut-picker-modal"], timeout=4.5,
                    desc="快捷选项面板"):
        print("[ai] ✓ 快捷选项面板已打开")
        return True
    print("[ai] ✗ 快捷选项面板没出现")
    _shot(page, "ai_shortcut_panel_missing")
    return False



def wait_shortcut_loaded(page: Page, timeout: float = 20.0,
                         poll: float = 0.1, keyword: str = "") -> int:
    """★ 等「快捷选项」面板把提示词列表加载出来。

    ★★ 2026-10-05 用户报障修复：「有时候加载不出来，导致根本没选上」。
      用户实测 + 本机逐帧探针坐实：面板是**分批渲染**的，实测时序
        t=0.01s 行数= 0
        t=0.20s 行数=11     ← 第一批
        t=0.26s 行数=26     ← 第二批
      老判据是「行数连续两次一致且 >0 就返回」⇒ **0.2 秒就返回了**。
      如果目标提示词恰好在**后面的批次**里（这里是第 12~26 条），
      返回时它还没渲染 ⇒ `pick_shortcut` 的 filter 命中 0 条
      ⇒ 判「面板里没有含 xx 的提示词」⇒ **静默跳过、根本没选上**。
      这跟用户看到的「点击后没加载出来」，本质是同一件事。

    ★ 修复：有明确 `keyword` 时，判据升级为「**目标那一行已经渲染出来**」——
      这才是真正要等的东西；行数稳定只是副产品。
      （`keyword` 为空时保留老的「行数稳定」判据，因为没有明确目标。）

    ★ 效率改造（本轮）：原实现是「数一次 → **固定 sleep 1.0s** → 再数一次」，
      也就是**每次调用至少吃掉 1 秒**，而且是 `poll=1.5` 的粗轮询。
      现在改成**短间隔连续两次计数稳定**即返回：
        * 每 0.1s 数一次；
        * 连续两次计数相同（≥1）→ 认为渲染完成，立刻返回；
        * 列表已经加载好的情况下 ≈0.1~0.2 秒就返回（原来固定 1 秒）。
      仍然保留"稳定性确认"，因为 Naive UI 确实会分批渲染。

    Returns:
        int 加载出来的行数（超时返回当前值）

    ★★ 20 秒死等修复（2026-10-04 实测）：
      本函数只判断「行数稳定」，**不判断面板是否存在**。所以一旦面板
      根本没打开（例如下拉被残留遮罩拦住），它会**一直数到 timeout=20 秒**
      才返回 0。实测 `pick_review_requirement` 因为这个原因，
      3 次调用白等了 **57.9 秒**（579 次 0.1s 轮询）。
      现在：先确认面板在不在；短暂等待后仍不在 → 立刻返回 0 并告警。
    """
    rows = page.locator(".shortcut-picker-modal .prompt-row")

    # ★ 面板存在性前置检查：不在就别数了（省下整个 timeout）
    if not page.locator(".shortcut-picker-modal").count():
        probe = wait_until(
            lambda: page.locator(".shortcut-picker-modal").count() > 0,
            timeout=min(float(timeout), 3.0), interval=0.08,
            desc="提示词面板出现")
        if not probe.ok:
            print("[ai] ⚠ 提示词面板没有打开 → 跳过列表等待"
                  f"（省下 {timeout:.0f} 秒死等）")
            return 0

    t0 = time.time()
    last = -1
    stable = 0
    while time.time() - t0 < timeout:
        # ★★ 2026-10-05：有明确目标时，**目标行出现就算加载完成**（首选判据）
        if keyword:
            try:
                if rows.filter(has_text=keyword).count() > 0:
                    n = rows.count()
                    print(f"[ai] ✓ 目标提示词已渲染（{n} 项，{time.time()-t0:.2f}s）")
                    return n
            except Exception:
                pass
            # ★ 提前退出（省时间）：行数已经**连续一段时间没变**，且这期间
            #   目标始终不出现 ⇒ 列表已渲染完、这个关键词就是没有。
            #   实测：真不存在时若死等 8s，白等；改为「稳定 1.5s 即退」。
            try:
                n = rows.count()
            except Exception:
                n = -1
            if n != last:
                last = n
                stable = 0
            else:
                stable += 1
            if n >= 0 and stable >= int(1.5 / max(poll, 0.01)):
                print(f"[ai] ⚠ 列表已渲染完（{n} 项）但仍无「{keyword}」"
                      f"→ 提前结束等待（{time.time()-t0:.2f}s）")
                return n
            time.sleep(poll)
            continue

        try:
            n = rows.count()
        except Exception:
            n = 0
        if n != last:
            print(f"[ai]   快捷选项面板已加载 {n} 项…")
            last = n
            stable = 0
        else:
            stable += 1
        # 连续 2 次计数一致且非空 → 视为渲染完成（省掉原来的固定 1 秒）
        if n > 0 and stable >= 2:
            print(f"[ai] ✓ 快捷选项加载完成（{n} 项）")
            return n
        time.sleep(poll)
    # ★ 超时也要给出准确信息：是「一行没有」还是「有行但目标没出现」
    if keyword:
        try:
            n = rows.count()
        except Exception:
            n = 0
        print(f"[ai] ⚠ 等目标提示词超时（{timeout:.1f}s，面板现有 {n} 项）")
        return n
    print(f"[ai] ⚠ 快捷选项加载超时（{last} 项）")
    return max(last, 0)



def close_shortcut_panel(page: Page) -> None:
    """关掉快捷选项面板（ESC）。

    ★ 效率改造（2026-10-04）：原来固定 sleep(0.6) 等面板关。
      改成条件等待「面板真的消失」——通常几十毫秒就返回。
    """
    try:
        if page.locator(".shortcut-picker-modal").first.count():
            page.keyboard.press("Escape")
            wait_gone(lambda: page.locator(".shortcut-picker-modal")
                      .first.is_visible(timeout=60),
                      timeout=1.5, interval=0.05, desc="快捷选项面板关闭")
    except Exception:
        pass



def pick_shortcut(page: Page, keyword: str = "", index: int = 0,
                  search_first: bool = False,
                  panel_already_open: bool = False,
                  verify_row: bool = True) -> bool:
    """★ 用**文字定位**在「快捷选项」面板里选中一个提示词。

    Args:
        keyword:      提示词里的关键词（支持部分文字 / 模糊）。
                      留空则选第 index 个（不推荐，顺序会变）。
        index:        文字命中多个时选第几个（从 0 开始）
        search_first: True 则先在面板搜索框里搜一下，再点（列表很长时更稳）
        panel_already_open: 面板已经开着就别再点一次
        verify_row:   ★ 是否回读「快捷选项那一行」做断言。
                      续写场景（True）该行就是面板的宿主，能对上；
                      审稿场景（False）宿主是审稿面板，回读必空 → 跳过。

    Returns:
        bool 是否成功选中

    ★ 为什么用文字定位：
        站点列表顺序、收藏数、运营推荐都会变，记「第几行」必然失效；
        用关键词找行，什么情况都能点到。
    """
    print(f"[ai] --- 选快捷选项：{keyword!r} ---")

    # ★★ 已选则跳过（2026-10-04 用户需求）：
    #   如果「快捷选项那一行」已经显示了含关键词的提示词，就不再打开面板重选。
    #   注意：仅在续写场景有效（verify_row=True 时那一行就是宿主）；
    #   审稿场景（verify_row=False）宿主不同，这里跳过回读判断。
    if keyword and verify_row:
        cur_shortcut = current_shortcut(page)
        if cur_shortcut and keyword in cur_shortcut:
            print(f"[ai] ✓ 快捷选项已是「{cur_shortcut[:40]}」，跳过重复选择")
            return True

    if not panel_already_open:
        if not open_shortcut_panel(page):
            return False

    # ★★ 必须等列表加载完（实测：打开瞬间是 0 项 + 「正在加载收藏提示词…」）
    #   ★★ 2026-10-05：把 keyword 传进去 —— 有明确目标时等的是
    #      「**目标那一行**已渲染」，而不是「行数稳定」。
    #      逐帧探针坐实：行数 0→11(稳定,0.2s)→26，老判据 0.2s 就返回，
    #      目标若在第 12~26 条里就**根本没渲染出来**，后续 filter 命中 0 →
    #      静默跳过（= 用户说的「根本没选上」）。
    #   ★ 超时给 8s（不是默认 20s）：实测正常 0.2~0.6s 就绪；真没有这个
    #     提示词时，等 8s 足够，不必白等 20s（下面还有补等+滚动兜底）。
    n_loaded = wait_shortcut_loaded(page, timeout=8.0, keyword=keyword)

    # ★ 补一次机会：面板可能被"点开了但内容还在请求"，或者首屏渲染恰好
    #   卡在第一批。给一次针对性补等（只等目标行，超时很短），
    #   避免直接掉进「找不到 → 跳过」。
    if keyword and n_loaded == 0:
        print("[ai] ⚠ 面板还没渲染出任何行 → 补等一次")
        wait_shortcut_loaded(page, timeout=4.0, keyword=keyword)

    # ① 可选：先用搜索框缩小列表
    if search_first and keyword:
        try:
            sb = page.locator(AI_SELECTORS["shortcut_search"][0]).first
            if sb.count() and sb.is_visible():
                sb.click(timeout=CLICK_FAST_TIMEOUT)
                sb.fill("")
                sb.type(keyword, delay=40)
                # 点搜索按钮或回车
                try:
                    page.locator(
                        ".shortcut-picker-modal button:has-text('搜索')").first.click(
                        timeout=2000)
                except Exception:
                    sb.press("Enter")
                # ★ 效率改造：原来固定等 1.5s 等搜索结果。改为等列表刷新，
                #   即「出现含关键词的行」或「行数稳定」——一满足就继续。
                wait_until(
                    lambda: (page.locator(
                        ".shortcut-picker-modal .prompt-row").filter(
                            has_text=keyword).count() > 0),
                    timeout=4.0, interval=0.08, desc="搜索结果出现")
                print(f"[ai] ✓ 已在面板里搜索：{keyword}")
        except Exception as e:
            print(f"[ai] ⚠ 搜索失败（继续直接找）：{str(e).splitlines()[0]}")

    # ② 文字定位
    rows = page.locator(".shortcut-picker-modal .prompt-row")
    target = None
    matched_by = ""

    def _find_target():
        """按关键词找行；返回 (locator|None, 说明)。"""
        if not keyword:
            return None, ""
        m = rows.filter(has_text=keyword)
        n = m.count()
        if n:
            if index < n:
                return m.nth(index), f"has-text({keyword!r})"
            return m.first, f"has-text({keyword!r}) first"
        # 兜底：把关键词切成 2 字片段逐个试（应对站点改字，如 云霄/云哥）
        # ★ 但只认「片段命中数唯一」的情况，避免选错
        if len(keyword) >= 4:
            cands = []
            for i in range(len(keyword) - 1):
                frag = keyword[i:i + 2]
                if not frag.strip():
                    continue
                mm = rows.filter(has_text=frag)
                c = mm.count()
                if c == 1:
                    cands.append((frag, mm.first))
            if len(cands) == 1:
                return cands[0][1], f"片段 {cands[0][0]!r}（唯一命中）"
            if len(cands) > 1:
                return (cands[0][1],
                        f"片段 {cands[0][0]!r}（注意：{len(cands)} 个片段都能命中）")
        return None, ""

    if keyword:
        target, matched_by = _find_target()

        # ★★★ 2026-10-05 用户报障修复：一次没找到**不要立刻放弃**。
        #   面板行是**虚拟滚动**渲染的，目标可能还没进 DOM；
        #   也可能首屏只渲染了第一批（逐帧实测 0→11→26）。
        #   这里再给两轮「补等 + 滚动」的机会，然后才判「没有」。
        for _retry in range(2):
            if target is not None:
                break
            print(f"[ai] ⚠ 暂未找到含「{keyword}」的行 → 补等并滚动列表"
                  f"（第 {_retry + 1}/2 次）")
            wait_shortcut_loaded(page, timeout=2.0, keyword=keyword)
            # 把面板列表滚到底（虚拟滚动会把后面的行渲染出来）
            try:
                page.evaluate("""() => {
                  const m = document.querySelector('.shortcut-picker-modal');
                  if (!m) return;
                  const cands = m.querySelectorAll(
                      '.n-scrollbar-container, .prompt-row, .n-virtual-list');
                  for (const c of cands) {
                    try { c.scrollTop = c.scrollHeight; } catch (e) {}
                  }
                }""")
            except Exception:
                pass
            time.sleep(0.25)   # ★ 用户要求：「加一小点延迟」，等渲染
            target, matched_by = _find_target()

    if target is None:
        # ★ 有关键词却没命中 → 不选错，但也**不阻断主流程**
        #   （用户要求：有则改、没有就跳过，不影响进程）
        if keyword:
            n = rows.count()
            print(f"[ai] ⚠ 面板里没有含「{keyword}」的提示词（共 {n} 项，已补等+滚动）"
                  f"→ 跳过这一项，沿用当前提示词")
            _shot(page, "ai_shortcut_not_found")
            close_shortcut_panel(page)
            return False
        # 没给关键词时才按序号选
        n = rows.count()
        if not n:
            print("[ai] ✗ 面板里一个提示词都没有")
            _shot(page, "ai_shortcut_empty")
            close_shortcut_panel(page)
            return False
        if index >= n:
            print(f"[ai] ✗ index={index} 越界（共 {n} 项）")
            close_shortcut_panel(page)
            return False
        target = rows.nth(index)
        matched_by = f"第 {index} 项"

    # ③ 命中信息
    try:
        txt = _text_of(target, timeout=600).replace("\n", " | ")
    except Exception:
        txt = ""
    print(f"[ai] 命中（{matched_by}）：{txt[:60]!r}")

    # ④ 点它
    try:
        # ★ 效率改造（2026-10-04）：删掉固定 sleep(0.3)（列表已由
        #   wait_shortcut_loaded 等到稳定），并给滚动加短超时。
        target.scroll_into_view_if_needed(timeout=CLICK_FAST_TIMEOUT)
    except Exception:
        pass

    def _do_click() -> bool:
        """点这一行（常规 → 行内标题 → force 三级降级）。"""
        try:
            target.click(timeout=CLICK_FAST_TIMEOUT)
            return True
        except Exception as e:
            print(f"[ai] ⚠ 常规点击失败：{str(e).splitlines()[0]}")
        try:
            t = target.locator(".row-title").first
            if t.count():
                t.click(timeout=3000)
                return True
        except Exception:
            pass
        try:
            target.click(force=True, timeout=3000)
            return True
        except Exception as e2:
            print(f"[ai] ✗ 点不动这一行：{str(e2).splitlines()[0]}")
        return False

    ok_click = _do_click()
    if not ok_click:
        _shot(page, "ai_shortcut_click_failed")
        return False

    def _wait_panel_closed(t: float = 1.5) -> None:
        """等面板收起（纯信号，不作成败判据）。"""
        wait_gone(
            lambda: any(page.locator(s).first.is_visible(timeout=60)
                        for s in AI_SELECTORS["shortcut_panel"]
                        if page.locator(s).count()),
            timeout=t, interval=0.05, desc="快捷选项面板收起")

    def _read_back() -> str:
        """回读当前选中态：续写读「续写要求」行，审稿读「审稿要求」行。"""
        if verify_row:
            return current_shortcut(page)
        return current_review_requirement(page)

    def _matches(after: str) -> bool:
        """回读值是否命中这一行（关键词 / 整标题 / 标题核心词）。"""
        if not after:
            return False
        if keyword and (keyword in after):
            return True
        if want and (want == after or want_core == after_core):
            return True
        if want_core and len(want_core) >= 4 and want_core[:8] in after:
            return True
        return False

    # 点中行的标题（去掉「使用方法」等尾巴）
    want = txt.split("使用方法")[0].strip()
    want_core = want.split("（")[0].strip()          # 去掉（细腻优先…）

    # ★★★ 2026-10-05 用户报障修复：「点击后需要加一小点的延迟，
    #   不然有时候加载不出来，导致根本没选上」。
    #   做法：点完 → 等面板收起 → 回读；**没对上就再等、再点一次**。
    #   · 续写场景（verify_row=True）老代码本来就回读，这里补上重试；
    #   · 审稿场景（verify_row=False）老代码**完全不回读**（点完就 return True），
    #     用户说的"根本没选上"正是这个洞 —— 改成回读「审稿要求」那一行。
    _wait_panel_closed(1.5)
    wait_until(lambda: bool(_read_back()), timeout=1.0, interval=0.06,
               desc="提示词行刷新")

    after = _read_back()
    if _matches(after):
        print(f"[ai] ✓ 已选中「{(after or want)[:40]}」（回读确认）")
        return True

    # —— 第一轮回读没对上：给一次「延迟 + 重试点击」 ——
    print(f"[ai] ⚠ 回读未命中（当前「{(after or '(空)')[:30]}」）"
          f"→ 延迟后重试点击一次")
    time.sleep(0.6)                       # ★ 用户要求的那「一小点延迟」
    # 面板可能已收起 → 需要重新打开再点
    if not page.locator(".shortcut-picker-modal").count():
        try:
            if verify_row:
                # 续写场景：重开面板
                if not open_shortcut_panel(page):
                    _shot(page, "ai_shortcut_retry_no_panel")
                    return False
            else:
                # 审稿场景：重开那一行下拉
                _safe_click(page.locator(AI_SELECTORS["review_selects"][0]).nth(1),
                            label="审稿要求下拉(重试)")
                wait_visible(page, AI_SELECTORS["shortcut_panel"],
                             timeout=3.0, desc="审稿要求面板(重试)")
            wait_shortcut_loaded(page, timeout=6.0, keyword=keyword)
        except Exception as e:
            print(f"[ai] ⚠ 重试前重开面板失败：{str(e).splitlines()[0]}")

    t2, mb2 = _find_target()
    if t2 is not None:
        target = t2
        try:
            target.scroll_into_view_if_needed(timeout=CLICK_FAST_TIMEOUT)
        except Exception:
            pass
        ok_click = _do_click()
        _wait_panel_closed(1.5)
        wait_until(lambda: bool(_read_back()), timeout=1.0, interval=0.06,
                   desc="提示词行刷新(重试)")
        after = _read_back()
        if _matches(after):
            print(f"[ai] ✓ 重试后已选中「{(after or want)[:40]}」（回读确认）")
            return True
        print(f"[ai] ✗ 重试后仍未命中（当前「{(after or '(空)')[:30]}」）")
    else:
        print("[ai] ✗ 重试时找不到目标行")

    # ★ 最后一层：ok_click 成功但回读对不上 —— 对续写场景而言回读是硬判据
    #   （老行为：返回 False 让上层决定）；审稿场景回读宿主不同、
    #   偶尔读不到（老代码就完全不信回读），这里保持"点击成功即算过"，
    #   但要打醒目的告警，别静默。
    if not verify_row and ok_click:
        print("[ai] ⚠ 审稿要求回读未命中，但点击已成功 → 按已选处理（请留意）")
        _shot(page, "ai_review_req_unverified")
        return True

    if after:
        print(f"[ai] ✗ 点了「{want[:30]}」但当前显示「{after[:30]}」，没对上")
    else:
        print("[ai] ✗ 回读不到快捷选项（可能没切成功）")
    _shot(page, "ai_shortcut_switch_failed")
    return False

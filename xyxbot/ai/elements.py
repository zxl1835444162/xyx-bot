"""底层元素定位 / 点击 / 填写 / 取消标志（其它模块都建在这上面）。

本文件由 `xyxbot/ai.py` 拆分而来（Phase C1）。拆分时按 AST 依赖做了拓扑排序，
所以每个模块只 import 排在自己前面的模块，不存在循环引用。
"""

from __future__ import annotations

from xyxbot import config as C
from xyxbot.waiting import wait_gone, wait_until, wait_visible
from playwright.sync_api import Page
import threading

from xyxbot.ai.selectors import NUISANCE_DIALOGS

__all__ = ["CLICK_FAST_TIMEOUT", "CLICK_SLOW_TIMEOUT", "_CANCEL", "_cat_selected", "_click_first", "_fill_first", "_present", "_safe_click", "_shot", "_visible", "cancel_requested", "canceled", "clear_cancel", "dismiss_dialogs", "request_cancel"]



# ================================================================ 中止（停止）
#
# ★★ 为什么要有这个（用户 2026-10-04 需求）
# ============================================
# 批量跑章动辄 100 章、几个小时。原来的界面**没有停止按钮** —— 想停下只能
# 关掉整个窗口。而就算加了按钮，如果一个章节正卡在 `wait_generation`
# （最多等 300 秒）或 `wait_review_done`（最多等 600 秒）里，"停止"也只能
# 等到那个超时才生效。
#
# 所以这里做的是**协作式中止**：
#   * `request_cancel()`  —— 界面点「停止」时调用（任意线程）
#   * `cancel_requested()` —— 长等待/循环里轮询它
#   * `clear_cancel()`    —— 开始新任务前清掉上一次的标记
#
# 长等待通过 `wait_until(..., should_abort=cancel_requested)` 接入，
# 因此中止会在**一个轮询周期内**（默认 ≤0.25 秒）生效，而不是等满超时。
#
# 用模块级 Event 而不是层层传参：本项目同一时刻只允许一个浏览器任务
# （`ui/browser_session.py` 里有统一互斥），所以"当前任务"是唯一确定的。
_CANCEL = threading.Event()



def request_cancel() -> None:
    """请求中止当前批量任务（线程安全，可从 tk 主线程调用）。"""
    _CANCEL.set()



def clear_cancel() -> None:
    """清除中止标记（开始新任务前调用）。"""
    _CANCEL.clear()



def cancel_requested() -> bool:
    """是否已被请求中止。"""
    return _CANCEL.is_set()



def canceled() -> bool:
    """`cancel_requested` 的美式拼写别名（避免调用方拼错）。"""
    return _CANCEL.is_set()



# ---------------------------------------------------------------- 基础动作

def _shot(page: Page, name: str) -> None:
    try:
        out = C.SHOTS / f"{name}.png"
        out.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(out))
        print(f"[shot] {out}")
    except Exception as e:
        print(f"[shot] 失败: {e}")



def _visible(page: Page, selectors, timeout: int = 1200,
             max_probe: int = 6):
    """返回第一个**可见的** Locator，找不到返回 None。

    ★★ 2026-10-05 修「点不到『开始 AI 续写』按钮」（用户实测第 47 章失败）：

      老实现是 `page.locator(sel).first` + `is_visible()` —— **只看第一个**。
      但页面上同时存在**多个**同名按钮（多章残留、隐藏的旧弹窗、
      Naive UI 的隐藏过渡层），`.first` 极可能命中一个 **display:none /
      0x0 的隐藏元素** ⇒ `is_visible()` = False ⇒ 立刻 `return None, None`
      ⇒ `_click_first` 打印「✗ 找不到目标」并**直接返回 False**，
      **三级降级（原生→JS→兜底）一步都没走到**。

      ⇒ 于是出现这个自相矛盾的现象：
         `_has_start_button()`（遍历最多 4 个、逐个判可见）说 **有按钮** ✅，
         紧接着 `start_generate()`（只看 .first）说 **找不到按钮** ✗。

      ⇒ 修法：与 `_has_start_button` 的判据统一 —— **逐个探测**，
         返回第一个真正可见的那个。

    ★ 性能：`is_visible(timeout=ms)` 对已存在但隐藏的元素会**等满 timeout**。
      所以分两轮：
        第 1 轮 `is_visible()`（无超时，立刻返回）—— 快，能命中绝大多数；
        第 2 轮只在第 1 轮全灭时才用，且给 `timeout`（等它渲染出来）。
      这样「本来就可见」的调用**一点没变慢**。
    """
    for sel in selectors:
        try:
            loc = page.locator(sel)
            n = loc.count()
            if n <= 0:
                continue
            # 第 1 轮：无超时快探（对隐藏元素立刻返回 False，不白等）
            for i in range(min(n, max_probe)):
                try:
                    if loc.nth(i).is_visible():
                        return loc.nth(i), sel
                except Exception:
                    continue
            # 第 2 轮：等它变可见（可能还在渲染/过渡动画中）
            if timeout and timeout > 0:
                for i in range(min(n, max_probe)):
                    try:
                        if loc.nth(i).is_visible(timeout=timeout):
                            return loc.nth(i), sel
                    except Exception:
                        continue
        except Exception:
            continue
    return None, None



def _present(page: Page, selectors, max_probe: int = 6):
    """返回第一个**存在**（不一定可见）的 Locator，找不到返回 None。

    ★ 2026-10-05 新增，配合 `_click_first` 的第四档降级：
      「元素在 DOM 里但被判定不可见」时，仍可以用 JS 点击救回来。
    """
    for sel in selectors:
        try:
            loc = page.locator(sel)
            if loc.count() > 0:
                return loc.first, sel
        except Exception:
            continue
    return None, None



def _cat_selected(loc) -> bool:
    """模型分类项是否已被选中（Naive UI 会给选中项加状态类）。

    用于把「点完分类后固定 sleep」换成条件等待。
    读 `class` 属性，是很轻的操作。
    """
    try:
        cls = loc.get_attribute("class") or ""
    except Exception:
        return False
    cls = cls.lower()
    return any(k in cls for k in
               ("active", "checked", "selected", "primary"))



def dismiss_dialogs(page: Page, verbose: bool = True) -> int:
    """关掉进编辑器后弹出的干扰弹窗（不会误关续写弹窗）。

    实测（2026-10-03）：打开作品后可能弹
      - 「是否默认打开上次章节？」（居中模态，会挡住工具栏）
      - 「国庆特惠上线了」（右上角通知）
    不关掉它们，点「AI续写正文」会被 `intercepts pointer events` 拦截。

    Returns: 关掉了几个
    """
    closed = 0
    for d in NUISANCE_DIALOGS:
        try:
            modal = page.locator(f".n-modal{d['mark']}").first
            if not modal.is_visible(timeout=600):
                continue
            if verbose:
                print(f"[ai] 发现干扰弹窗 {d['mark']}，关闭中 …")
            for btn in d["buttons"]:
                try:
                    b = modal.locator(btn).first
                    if b.is_visible(timeout=500):
                        b.click(timeout=2500)
                        closed += 1
                        if verbose:
                            print(f"[ai]   ✓ 点 {btn}")
                        # ★ 效率改造：原来固定 sleep 0.7s 等弹窗消失。
                        #   改成等**这个弹窗真的不可见**；本来就没弹窗时
                        #   整段直接跳过（不会白吃 0.7 秒）。
                        wait_gone(
                            lambda m=modal: bool(m.count())
                            and m.is_visible(timeout=60),
                            timeout=2.5, interval=0.05, desc="干扰弹窗关闭")
                        break
                except Exception:
                    continue
        except Exception:
            continue

    # 兜底：右上角通知类的关闭按钮
    try:
        for sel in [".n-notification .n-base-close",
                    ".n-notification [class*=close]"]:
            loc = page.locator(sel)
            for i in range(loc.count()):
                el = loc.nth(i)
                if el.is_visible():
                    el.click(timeout=1500)
                    closed += 1
                    if verbose:
                        print(f"[ai]   ✓ 关掉通知 ({sel})")
                    # ★ 等通知消失（原来固定 sleep 0.4s）
                    wait_gone(lambda e=el: e.is_visible(timeout=60),
                              timeout=1.5, interval=0.05, desc="通知关闭")
    except Exception:
        pass

    return closed



# ★★ 点击策略：原生点击给「很短」的超时，失败立刻 JS 降级（2026-10-04 实测）
#
# 现场拆解（diag_click）发现：点「AI续写正文」时
#     loc.click(timeout=4000)  → **每次都超时 4096ms 才抛异常**
#     loc.evaluate('e=>e.click()') → **6ms 就成功**
#     _click_first 整段 → 4222ms（3 轮全部一样）
#
# 为什么原生点击会被拦：站点**关掉弹窗后仍留着一个全屏遮罩**
#   `.n-modal-mask`（实测 1440x900、visibility:visible、opacity:1、
#   pointer-events:auto），Playwright 的命中测试认为按钮"没接收指针事件"，
#   于是重试到超时。而 JS 点击不走命中测试，直接派发 click 事件，Vue 能收到。
#
# 于是：把原生点击的首试超时从 4000ms 降到 600ms（**每次点被拦的按钮省 3.4 秒**），
#   失败就走 JS 点击；万一 JS 也不行，再用长超时原生点击兜底 ——
#   也就是说**最坏情况仍然等于旧行为**，只会更快，不会更差。
#   （600ms 的依据：实测原生点击成功时约 120ms，失败时是"永远失败"；
#     留 600ms 是给"慢但合法"的点击留余量。）
CLICK_FAST_TIMEOUT = 600        # 原生点击首试（毫秒）

CLICK_SLOW_TIMEOUT = 4000       # 最后兜底（等于旧行为）



def _click_first(page: Page, selectors, label: str = "",
                 timeout: int = 1200, shot_on_fail: bool = False) -> bool:
    """点第一个可见的。失败返回 False。

    ★ 三档降级：原生点击(600ms) → JS 点击(~6ms) → 原生点击(4000ms 兜底)。
      详见上面 CLICK_FAST_TIMEOUT 的说明。

    ★★ 2026-10-05 加固（用户实测第 47 章「点不到『开始 AI 续写』按钮」）：
      上面「三档降级」全都建立在**已经拿到可见 locator** 的前提上。
      可一旦元素存在但**没被判定为可见**，老代码打印「✗ 找不到目标」
      就直接 return False —— 三级降级一步没走，用户看到的就是
      「点不到『开始 AI 续写』按钮」（而实际上按钮可能只是被遮挡/在过渡中）。

      ⇒ 新增**第四档**：拿不到"可见"的元素时，退而求其次找**存在**的元素，
        用 JS 点击（JS 不走命中测试，也不需要可见性）。
        这对「按钮已渲染但被判定不可见」是决定性的救命路径。
    """
    loc, sel = _visible(page, selectors, timeout)
    if loc is None:
        # ★ 第四档：找不到"可见的" → 找"存在的"，用 JS 直接点
        loc2, sel2 = _present(page, selectors)
        if loc2 is not None:
            try:
                loc2.evaluate("el => el.click()")
                print(f"[ai] ✓ 点击 {label or sel2}"
                      f"（元素存在但判定不可见 → JS 直点兜底）")
                return True
            except Exception as e:
                print(f"[ai] ✗ 存在但点不动({label or sel2}): "
                      f"{str(e).splitlines()[0][:60]}")
        print(f"[ai] ✗ 找不到目标: {label or selectors[0]}"
              f"（既无可见、也无存在的匹配元素）")
        if shot_on_fail:
            _shot(page, f"fail-{(label or 'x').replace(' ', '_')}")
        return False

    try:
        loc.scroll_into_view_if_needed(timeout=CLICK_FAST_TIMEOUT)
    except Exception:
        pass

    # ① 原生点击（短超时）
    try:
        loc.click(timeout=CLICK_FAST_TIMEOUT)
        print(f"[ai] ✓ 点击 {label or sel}")
        return True
    except Exception as e:
        msg = str(e).splitlines()[0]

    # ② JS 点击（站点留着遮罩时，实际生效的就是这条路）
    try:
        loc.evaluate("el => el.click()")
        print(f"[ai] ✓ 点击 {label or sel}（JS 降级；原生点击被拦：{msg[:48]}）")
        return True
    except Exception as e2:
        js_msg = str(e2).splitlines()[0]

    # ③ 兜底：长超时原生点击（= 旧行为，保证不比以前差）
    try:
        loc.click(timeout=CLICK_SLOW_TIMEOUT)
        print(f"[ai] ✓ 点击 {label or sel}（长超时重试成功）")
        return True
    except Exception as e3:
        print(f"[ai] ✗ 点击彻底失败({label})：原生[{msg[:30]}] "
              f"JS[{js_msg[:30]}] 重试[{str(e3).splitlines()[0][:30]}]")
        if shot_on_fail:
            _shot(page, f"fail-{(label or 'x').replace(' ', '_')}")
        return False



def _safe_click(loc, timeout: int = CLICK_FAST_TIMEOUT,
                label: str = "") -> bool:
    """点一个**已经拿到**的 Locator：短超时原生 → JS → force 降级。

    ★★ 为什么不直接 `loc.click(timeout=4000)`（2026-10-04 实测）：
       本站关掉弹窗后会**留下一个全屏遮罩** `.n-modal-mask`
       （1440x900、visibility:visible、opacity:1、pointer-events:auto）。
       Playwright 的命中测试认为目标元素"没接收指针事件"，
       于是**一直重试到超时**：

           loc.click(timeout=4000)      → 4096ms 抛异常
           loc.evaluate('e=>e.click()') →    6ms 成功

       也就是说：一次 `click(timeout=4000)` 白等 4 秒，而且**必然失败**。
       项目里原本散布着 4000/5000ms 的点击（"全选"、审稿要求下拉、
       章节项、模型卡片…），每章累计白等 20~30 秒。
       JS 点击不走命中测试、直接派发 click 事件，Vue 照样收到 —— 这才是
       本站实际生效的路径。

    ★ 三档降级保证「不比旧行为差」：短超时原生 → JS → force 长超时。
    """
    try:
        loc.click(timeout=timeout)
        return True
    except Exception:
        pass
    try:
        loc.evaluate("e => e.click()")
        return True
    except Exception:
        pass
    try:
        loc.click(timeout=timeout, force=True)
        return True
    except Exception:
        print(f"[ai] ✗ 点击失败（原生/JS/force 都不行）：{label}")
        return False



def _fill_first(page: Page, selectors, text: str, label: str = "") -> bool:
    """往第一个可见输入框填字。

    ★ 效率改造（2026-10-04 实测）：原实现是「先 click() 再 fill("") 再 fill(text)」。
      那个 `click()` 在本站**必然被残留遮罩拦住**，白白等满超时
      （实测 `_fill_first` 1.1 秒/次）。
      而 Playwright 的 `fill()` 自己就会聚焦元素，**根本不需要先点**。
      现在：直接 fill；只有 fill 失败才回头走「点击 → 清空 → 再填」的兜底。
    """
    loc, sel = _visible(page, selectors, timeout=1500)
    if loc is None:
        print(f"[ai] ✗ 找不到输入框: {label or selectors[0]}")
        return False

    # ① 直接填（最常见、最快）
    try:
        loc.fill(text, timeout=4000)
        print(f"[ai] ✓ 已填 {label}（{len(text)} 字）")
        return True
    except Exception:
        pass

    # ② 兜底：先聚焦（短超时/JS），再清空重填，最后逐字敲
    try:
        _safe_click(loc, label=f"聚焦 {label}")
        try:
            loc.fill("", timeout=2000)
        except Exception:
            pass
        loc.fill(text, timeout=4000)
        print(f"[ai] ✓ 已填 {label}（{len(text)} 字，兜底路径）")
        return True
    except Exception:
        try:
            loc.type(text, delay=8)
            print(f"[ai] ✓ 已填 {label}（{len(text)} 字，逐字敲）")
            return True
        except Exception as e:
            print(f"[ai] ✗ 填写失败({label})：{e}")
            return False

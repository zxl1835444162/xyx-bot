"""审稿要求：切 tab / 点下拉行 / 用文字定位选提示词。

本文件由原巨型模块拆分而来（Phase C2/C1），拆分时按 AST 依赖做了拓扑排序，
每个模块只 import 排在自己前面的模块，不存在循环引用。
"""

from __future__ import annotations

from playwright.sync_api import Page
from xyxbot.ai.current import _text_of, current_review_requirement
from xyxbot.ai.elements import CLICK_FAST_TIMEOUT, _fill_first, _safe_click, _shot, cancel_requested, dismiss_dialogs
from xyxbot.ai.selectors import AI_SELECTORS, ANCHOR_TEXT, REVIEW_CARD_ALT, REVIEW_CARD_SEL, REVIEW_PANE_SEL, REVIEW_SEP
from xyxbot.ai.shortcuts import pick_shortcut
from xyxbot.waiting import wait_gone, wait_until, wait_visible

__all__ = ["_open_review_req_row", "_switch_review_tab", "pick_review_requirement"]




def _switch_review_tab(page: Page, tab: str) -> None:
    """① 切到「审稿要求」的某个 tab，并等下拉行渲染出来。

    ★ 必须**按文字点，不用 class**：Naive UI 里「快捷选项」和「更多」会**同时**
      带 `--checked`，按 class 判断选中态一定出错。
    ★ 实测：`{面板} .n-radio-button:has-text(...)` 常点击超时 —— tab 在抽屉内但
      可能有遮挡/动画。改为 **JS 精确定位 + 原生点击**，失败再降级到
      Playwright 短超时点击（+ JS/force 兜底，别白等 3 秒）。
    ★ 效率改造：原来切 tab 后固定 sleep 0.5s。改成等**下拉行真的渲染出来**
      （tab 切换生效的可见信号）：2 个 .n-base-selection 都出现即可。
      找不到也无妨（后面有判空）。
    """
    tab_ok = False
    try:
        tab_ok = bool(page.evaluate("""(payload) => {
          const [anchor, label] = payload;
          const pane = [...document.querySelectorAll('.n-card-content')]
              .find(c => c.innerText.includes(anchor));
          if (!pane) return false;
          const t = [...pane.querySelectorAll('.n-radio-button')]
              .find(e => e.innerText.trim() === label);
          if (!t) return false;
          t.scrollIntoView({block: 'center'});
          t.click();
          return true;
        }""", [ANCHOR_TEXT, tab]))
        if tab_ok:
            print(f"[ai] ✓ 已切到「{tab}」tab（JS 点击）")
    except Exception as e:
        print(f"[ai] ⚠ JS 点 tab 失败：{str(e).splitlines()[0]}")

    if not tab_ok:
        # 降级：Playwright 短超时点击（+ JS/force 兜底，别白等 3 秒）
        try:
            tab_loc = page.locator(
                f"{REVIEW_PANE_SEL} .n-radio-button").filter(has_text=tab).first
            if tab_loc.count():
                if _safe_click(tab_loc, label=f"「{tab}」tab"):
                    print(f"[ai] ✓ 已切到「{tab}」tab（降级点击）")
            else:
                print(f"[ai] ⚠ 找不到「{tab}」tab，沿用当前")
        except Exception as e:
            print(f"[ai] ⚠ 点 tab 失败：{str(e).splitlines()[0]}，沿用当前")

    wait_until(lambda: page.locator(
        AI_SELECTORS["review_selects"][0]).count() >= 2,
        timeout=2.0, interval=0.05, desc="审稿要求行就绪")



def _open_review_req_row(page: Page, keyword: str) -> str:
    """② 点「审稿要求」那一行下拉（★ 第 2 个 .n-base-selection）。

    返回：
      "fail"   —— 找不到那一行（已截图），调用方直接返回 False
      "done"   —— 那一行**已经是目标**了，不必重点，调用方直接返回 True
      "opened" —— 已点开面板，调用方继续走到「选提示词」
    """
    try:
        sels = page.locator(AI_SELECTORS["review_selects"][0])
        if sels.count() < 2:
            print("[ai] ✗ 找不到「审稿要求」那一行下拉")
            _shot(page, "ai_review_req_row_missing")
            return "fail"
        row = sels.nth(1)
        # 已经是目标了 → 跳过（回读断言，避免白点）
        cur = _text_of(row, timeout=400)
        if keyword and keyword in cur:
            print(f"[ai] 审稿要求已是「{cur[:40]}」，跳过")
            return "done"
        # ★ 短超时 + JS 降级（否则残留遮罩会让这里白等 4 秒，
        #   进而导致下面的面板等待/列表等待全部超时 —— 实测该步骤 29 秒）
        _safe_click(row, label="审稿要求下拉")
        print("[ai] ✓ 已打开审稿要求面板")
        # ★ 效率改造：原来固定 sleep 0.8s 等面板。改成等快捷选项面板出现。
        wait_visible(page, AI_SELECTORS["shortcut_panel"],
                     timeout=3.0, desc="审稿要求面板")
    except Exception as e:
        print(f"[ai] ✗ 点审稿要求失败：{str(e).splitlines()[0]}")
        _shot(page, "ai_review_req_open_fail")
        return "fail"
    return "opened"



def pick_review_requirement(page: Page, keyword: str = "",
                            tab: str = "快捷选项") -> bool:
    """选「审稿要求」里的提示词（★ 默认用「快捷选项」tab）。

    ★ 实测（2026-10-03）：
      ① 「审稿要求」下面有三个 tab：快捷选项 / 自定义 / 更多
         - 快捷选项：点开是**全屏提示词面板**（跟续写那边同一个 .prompt-row 列表）
         - 自定义：自己写一段要求
         - 更多：另一组预设
      ② 必须**先点 tab**，那一行下拉才会出现/切换。
      ③ ★ Naive UI 的样式怪癖：「快捷选项」和「更多」会**同时**带
         `--checked`，所以绝不能按 class 判断选中态，只能**按文字点**。

    Args:
        keyword: 提示词关键词（如「强盛集团云霄拯救过稿计划」）
        tab:     用哪个 tab，「快捷选项」/「自定义」/「更多」
    """
    print(f"[ai] --- 审稿要求：{tab} → {keyword or '(不改)'} ---")

    # ① 点 tab（判据与坑见 _switch_review_tab 的文档串）
    _switch_review_tab(page, tab)

    if not keyword:
        return True

    # ② 点那一行下拉
    _row = _open_review_req_row(page, keyword)
    if _row == "fail":
        return False
    if _row == "done":
        return True

    # ③ 用文字定位选提示词（复用续写的逻辑；★ verify_row=False → 内部回读
    #    「审稿要求」那一行，并在没对上时延迟重试一次）
    ok = pick_shortcut(page, keyword=keyword, panel_already_open=True,
                       verify_row=False)

    # ④ 回读断言（pick_shortcut 内部已等过，这里再确认一次最终态）
    after = current_review_requirement(page)
    if after and (keyword in after):
        print(f"[ai] ✓ 审稿要求已切换：{after[:50]}")
        return True
    print(f"[ai] ⚠ 审稿要求回读：「{after[:50]}」（目标含「{keyword}」）")
    return ok

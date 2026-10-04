"""星月写作 —— AI 续写正文自动化。

流程（每一步都实测过选择器）：

    1. 进编辑器页（用 books.open_book）
    2. 点顶部「AI续写正文」按钮
    3. 在弹窗里：
       a. 选「快捷选项」（提示词）—— ★ 用文字定位，见 pick_shortcut()
       b. 选模型 → 打开模型面板 → 点「细腻版」→ 点「使用此模型」
       c. 填「后续剧情」= 前缀 + 内容 + 后缀
       d. 关联章节 → 展开 → 点箭头 → 选「最近10章」
       e. 点「开始 AI 续写」

★ 实测于 2026-10-03。关键选择器：

| 元素 | 选择器 |
|---|---|
| AI续写正文按钮 | `button:has-text('AI续写正文')` |
| 后续剧情输入框 | `.n-modal textarea[placeholder*='后续剧情走向']` |
| 模型选择器 | `.n-modal .n-base-selection` （显示当前版本名，如「奇想版」） |
| 细腻版（分类） | `span.flex-1.truncate:has-text('细腻版')` |
| 联想能力按钮 | `button:has-text('联想能力')` |
| 使用此模型 | `button:has-text('使用此模型')` |
| 关联章节头 | `button:has-text('关联章节')` |
| 章节数下拉箭头 | `button.h-9.w-7`（在「最近5章」右边） |
| 开始AI续写 | `button:has-text('开始 AI 续写')` |

★ 「快捷选项」（续写要求那一行）—— 实测反直觉，单独说：

| 元素 | 选择器 |
|---|---|
| 那一行（Naive n-select） | `.n-form-item:has-text('续写要求') .n-base-selection` |
| 弹出的全屏面板 | `.shortcut-picker-modal` |
| 面板里的提示词行 | `.shortcut-picker-modal .prompt-row` |
| 行内标题文字 | `.row-title` |
| 面板搜索框 | `.shortcut-picker-modal input[placeholder*='搜索']` |

**点那一行不弹下拉菜单，而是弹一个全屏 modal**；
面板里点中某一行 `.prompt-row` → 面板自动关 → 那一行显示改成该提示词名。
**定位方式：用文字**（`.prompt-row:has-text('关键词')`），
不记第几行 —— 因为列表顺序 / 收藏数 / 运营推荐都会变。
"""

from __future__ import annotations

import re
import threading
import time
from typing import Callable, List, Optional

from playwright.sync_api import Page

from . import actions as A
from . import config as C
from .waiting import wait_gone, wait_until, wait_visible

# ★ 最近一次「按字数自动决策」的详细结果（dict），供 GUI 显示用。
#   ai_continue() 保持返回 bool（兼容所有调用方），细节放这里。
LAST_DECISION: Optional[dict] = None


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

# ★ 「AI审稿」面板的文字锚点（提到这里，因为 AI_SELECTORS 里要用）。
#   类名 chapter-side-pane-c 是动态生成的、不可靠；
#   但「待审文本」这几个字是写死的 → 用它认面板。
#
#   ★★ 2026-10-03 实测的**两层锚点**（非常重要，别再搞混）：
#     REVIEW_PANE_SEL   = `.n-card-content:has-text('待审文本')`
#         → 「待审文本」那个**滚动内容区**。适合定位面板内的输入控件
#           （模型下拉 / 待审文本 textarea / 审稿要求下拉）。
#     REVIEW_CARD_SEL   = `.n-card:has(...)`  → **整个审稿卡片**
#         → 「生成」按钮在卡片的 `.n-card__footer`（底部固定栏），
#           **不在** `.n-card-content` 里！所以点生成必须用 CARD 这层。
ANCHOR_TEXT = "待审文本"
REVIEW_PANE_SEL = f".n-card-content:has-text('{ANCHOR_TEXT}')"

# ★★ 2026-10-03 实测（第二版，覆盖「生成前 / 生成后」两个阶段）：
#    审稿卡片 = `.n-card.chapter-side-pane-c`（在 .chapter-right-workspace 里）。
#    踩坑：一开始加了 `.chapter-side-pane-card` 后缀，但**生成完成后
#      这个类会消失**（DOM 探查证实：生成后 cls = "...chapter-side-pane-c"，
#      不带 -card），于是 `:has-text('待审文本')` 也失效
#      （结果区把「待审文本」标签换掉了）。
#    所以做两个锚点：
#      REVIEW_PANE_SEL  : 生成**前**的内容区（有「待审文本」）→ 定位输入控件
#      REVIEW_CARD_SEL  : 整个审稿卡片（生成前/后都在）→ 定位 footer 按钮
REVIEW_CARD_SEL = (".chapter-right-workspace "
                   ".n-card.chapter-side-pane-c")
# 兼容：若上面这条在某些版本失效，退回到「有 chapter-side-pane-card 的」
REVIEW_CARD_ALT = ".n-card.chapter-side-pane-card"

# ---------------------------------------------------------------- 选择器

AI_SELECTORS = {
    # 顶部工具栏
    "btn_continue": [
        "button:has-text('AI续写正文')",
        "[class*=header] button:has-text('AI续写正文')",
    ],
    # 弹窗内
    "dialog": [
        ".n-modal:has-text('续写正文')",
        "[role=dialog]:has-text('续写正文')",
        ".n-modal:has-text('后续剧情')",
    ],
    # 「后续剧情」textarea
    "plot_input": [
        ".n-modal textarea[placeholder*='后续剧情走向']",
        ".n-modal textarea[placeholder*='伏笔']",
        ".n-modal textarea",
    ],
    # 模型选择器（显示「奇想版」那个）
    "model_selection": [
        ".n-modal .n-base-selection",
        ".n-modal [class*=base-selection]",
    ],
    # 模型分类项（精确文字）
    "model_xini": [
        "span.flex-1.truncate:has-text('细腻版')",
        "text=细腻版",
    ],
    # 联想能力
    "btn_associate": [
        "button:has-text('联想能力')",
        "[class*=btn]:has-text('联想能力')",
    ],
    # 使用此模型
    "btn_use_model": [
        "button:has-text('使用此模型')",
    ],
    # 关联章节（点击展开）
    "assoc_chapter": [
        ".n-modal button:has-text('关联章节')",
        "button:has-text('关联章节')",
    ],
    # 章节数下拉箭头（最近5章右侧的 ⌄）
    "assoc_arrow": [
        ".n-modal button.h-9.w-7",
        "button.h-9.w-7",
    ],
    # 更快的直选按钮
    "assoc_3": ["button:has-text('最近3章')"],
    "assoc_5": ["button:has-text('最近5章')"],
    # ★ 快捷选项（续写要求那一行，Naive UI 的 n-select）
    "shortcut_row": [
        ".n-form-item:has-text('续写要求') .n-base-selection",
        ".n-form-item:has-text('续写要求') .n-select",
    ],
    # ★ 快捷选项面板（点上面那一行会弹出的全屏 modal）
    "shortcut_panel": [
        ".shortcut-picker-modal",
        ".n-modal.shortcut-picker-modal",
        ".n-card.shortcut-picker-modal",
    ],
    # ★ 面板里的提示词列表项（已收藏 / 最新 都是这个类）
    "shortcut_items": [
        ".shortcut-picker-modal .prompt-row",
    ],
    # 面板里的搜索框（可以先把目标搜出来，再点）
    "shortcut_search": [
        ".shortcut-picker-modal input[placeholder*='搜索']",
        ".shortcut-picker-modal .search-bar input",
    ],
    # 开始续写
    "btn_start": [
        "button:has-text('开始 AI 续写')",
        "button:has-text('开始AI续写')",
    ],
    # ★ 生成结果页（点开始之后出现的那个「AI 续写」结果弹窗）
    #   底部按钮栏：
    #     上一步 / 重新生成 / 继续追问 / 复制 / 对比 / 导出至作品
    #     / 推送至备忘录 / 采纳使用
    "gen_dialog": [
        ".n-modal:has-text('AI 续写')",
        ".n-modal:has-text('采纳使用')",
        ".n-modal:has-text('重新生成')",
    ],
    "btn_accept": [
        "button:has-text('采纳使用')",
    ],
    "btn_regen": [
        "button:has-text('重新生成')",
    ],
    # ★ 点「重新生成」会先弹一个「使用提示」确认框
    #   （「对生成结果不满意？查看视频教程…」+ [重新生成] [看教程]）
    #   必须再点里面的「重新生成」才真的重生成
    "regen_confirm_dialog": [
        ".n-modal:has-text('对生成结果不满意')",
        ".n-modal:has-text('使用提示')",
        ".n-modal:has-text('查看视频教程')",
    ],
    "regen_confirm_btn": [
        ".n-modal:has-text('对生成结果不满意') button:has-text('重新生成')",
        ".n-modal:has-text('使用提示') button:has-text('重新生成')",
    ],
    # ★ 生成内容的字数（右下角那个数字）
    #   关键：它挂在 **textarea** 上（`.n-input--textarea`），
    #   而输入框上的那个（如 "3 / 35"）挂在普通 input 上，两者不同
    "gen_word_count": [
        ".n-modal .n-input--textarea .n-input-word-count",
        ".n-modal textarea ~ * .n-input-word-count",
        ".n-modal .n-input-word-count",
    ],

    # ============================================================
    # ★ AI 审稿（2026-10-03 实测）
    #
    # ★★ 与「AI续写正文」最大的不同：审稿**不是弹窗**，是**右侧抽屉面板**，
    #    而且是内嵌在编辑器布局里的（走 n-split-pane），
    #    所以 **`.n-modal` / `[role=dialog]` 全都抓不到**！
    #
    #    面板容器链路（实测）：
    #      .chapter-right-workspace
    #        └ .chapter-side-pane（class 是动态生成的，不可靠 ✗）
    #           └ .n-card.chapter-side-pane-c
    #              └ .n-card-content   ← ★ 唯一稳定锚点
    #
    #    ★ 因此定位一律用**文字锚点**：
    #        `.n-card-content:has-text('待审文本')`
    #      （类名 chapter-side-pane-c 会变，文字不会）
    # ============================================================
    # 顶部工具栏的「AI审稿」按钮（与 AI续写正文 同级，都是 warning 型）
    "btn_review": [
        "button:has-text('AI审稿')",
        "[class*=header] button:has-text('AI审稿')",
    ],
    # 审稿面板本体（★ 文字锚点，不用动态类名）
    "review_pane": [
        ".n-card-content:has-text('待审文本')",
        ".n-card-content:has-text('审稿要求')",
    ],
    # 面板里的两个下拉：第 0 个 = AI模型，第 1 个 = 审稿要求
    "review_selects": [
        ".n-card-content:has-text('待审文本') .n-base-selection",
    ],
    # 待审文本 textarea
    "review_text": [
        ".n-card-content:has-text('待审文本') textarea",
    ],
    # 「审稿要求」三个 tab（Naive UI 的 radio-button 组）
    "review_tabs": [
        ".n-card-content:has-text('待审文本') .n-radio-button",
    ],
    # 底部「生成」按钮（蓝色 primary，文字就是「生成」）
    # ★★ 必须是**审稿卡片**里的「生成」按钮。
    #    踩坑（2026-10-03）：
    #      ① 一开始用全局 `button:has-text('生成')` → 命中了左栏章节菜单
    #         浮层里的「一键生成概要」，`.first` 点错。
    #      ② 改成锁 `REVIEW_PANE_SEL`（.n-card-content）后 → 又找不到，
    #         因为**「生成」在 .n-card__footer，不在 .n-card-content 里**！
    #    最终：用 REVIEW_CARD_SEL（整个卡片）→ 正好覆盖 footer。
    "btn_review_start": [
        f"{REVIEW_CARD_SEL} .n-card__footer button:has-text('生成')",
        f"{REVIEW_CARD_SEL} button:has-text('生成')",
    ],
    # 「高级功能」开关
    "review_switch": [
        ".n-card-content:has-text('待审文本') .n-switch",
    ],

    # ============================================================
    # ★ 正文编辑器（2026-10-03 实测）
    #
    #   编辑器正文 = **tiptap / ProseMirror**：
    #       `.tiptap.ProseMirror`  ← 就是那个 contenteditable
    #
    #   编辑器工具栏（正文上方第二排，y≈55）按钮一律用 **aria-label**
    #   ★★ 注意：是 `aria-label`，**不是 `title`**（踩过坑！）
    #       x≈316 撤回 / 354 撤销撤回 / 392 复制 /
    #       **437 全选** / 475 搜索 /
    #       **520 替换**（★ 这是编辑器「查找替换」，跟审稿的
    #                    「替换 / 插入」**完全不是一回事**，别搞混！）/
    #       558 词条库 / 603 角色库 / 641 高频词透镜 /
    #       679 统一中文标点 / 717 智能排版
    # ============================================================
    "editor_body": [
        ".tiptap.ProseMirror",
        "div[contenteditable='true']",
    ],
    # ★ 正文工具栏的「全选」按钮（aria-label，不是 title）
    "btn_editor_select_all": [
        "button[aria-label='全选']",
        "button[title='全选']",
    ],
    # ★ 章节列表项（审稿前需要先打开一章，否则正文为空）
    # ★ 用**容器** `.chapter-item`（实测宽 274px，好点）；
    #   标题 `.chapter-item__title` 只有 36px，容易点偏。
    "chapter_item": [
        ".chapter-item",
        ".chapter-item__title",
    ],
    # ★★ 审稿生成完成后的「替换 / 插入」按钮（2026-10-03 真机实测）
    #    DOM 探查结果：
    #      t   = "替换 / 插入"（★ 注意：中间是「空格 / 空格」）
    #      cls = "n-button n-button--success-type n-button--small-type"
    #      位置 = .n-card__footer → .n-card.chapter-side-pane-c
    #      坐标 = x≈1265, y≈853（抽屉右下角）
    #    → 用**类名 + 文字**双保险；文字里去掉空格用 JS 匹配最稳。
    "btn_review_replace": [
        f"{REVIEW_CARD_SEL} .n-card__footer "
        f"button.n-button--success-type",
        f"{REVIEW_CARD_SEL} button.n-button--success-type",
        f"{REVIEW_CARD_SEL} button:has-text('替换')",
        f"{REVIEW_CARD_ALT} button:has-text('替换')",
    ],
    # 「替换」前的二次确认框（有则点、没有就跳过）
    "review_replace_confirm": [
        ".n-modal:has-text('替换') button:has-text('确认')",
        ".n-modal:has-text('替换') button:has-text('确定')",
        ".n-modal:has-text('替换') button:has-text('替换')",
        ".n-modal:has-text('覆盖') button:has-text('确定')",
    ],
    # 审稿「生成中」判据
    "review_generating": [
        f"{REVIEW_CARD_SEL} button:has-text('停止生成')",
        f"{REVIEW_CARD_SEL}:has-text('思考中')",
        f"{REVIEW_CARD_SEL}:has-text('生成中')",
    ],
}


# ---------------------------------------------------------------- 基础动作

def _shot(page: Page, name: str) -> None:
    try:
        out = C.SHOTS / f"{name}.png"
        out.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(out))
        print(f"[shot] {out}")
    except Exception as e:
        print(f"[shot] 失败: {e}")


def _visible(page: Page, selectors, timeout: int = 1200):
    """返回第一个可见的 Locator，找不到返回 None。"""
    for sel in selectors:
        try:
            loc = page.locator(sel).first
            if loc.is_visible(timeout=timeout):
                return loc, sel
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


# 进编辑器后可能弹出的干扰弹窗（实测）
NUISANCE_DIALOGS = [
    # 「是否默认打开上次章节？」
    {
        "mark": ":has-text('是否默认打开上次章节')",
        "buttons": ["button:has-text('暂不开启')", "button:has-text('开启')",
                    "[class*=close]"],
    },
    # 「国庆特惠」运营通知
    {
        "mark": ":has-text('国庆特惠')",
        "buttons": ["[class*=close]", "button[aria-label='close']"],
    },
    {
        "mark": ":has-text('特惠上线')",
        "buttons": ["[class*=close]", "button[aria-label='close']"],
    },
]


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

    ★ 三档降级：原生点击(900ms) → JS 点击(~6ms) → 原生点击(4000ms 兜底)。
      详见上面 CLICK_FAST_TIMEOUT 的说明。
    """
    loc, sel = _visible(page, selectors, timeout)
    if loc is None:
        print(f"[ai] ✗ 找不到目标: {label or selectors[0]}")
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


# ---------------------------------------------------------------- 流程步骤

def _stale_result_present(page: Page) -> bool:
    """★ 弹窗里是否残留着**上一轮的结果页**。

    判据：同一个弹窗里同时有「重新生成」和「采纳使用」按钮
    （这正是 `gen_finished` 的完成标志）。

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
        modal = page.locator(".n-modal").first
        if not modal.count():
            return False
        has_regen = bool(modal.locator("button:has-text('重新生成')").count())
        has_accept = bool(modal.locator("button:has-text('采纳使用')").count())
        return has_regen and has_accept
    except Exception:
        return False


def _close_stale_result(page: Page) -> bool:
    """关掉残留的结果弹窗，给新弹窗让路。

    优先点右上角关闭 / 取消；都没有就按 ESC。

    Returns: 是否执行了关闭动作
    """
    print("[ai] ⚠ 发现上一轮的结果页还开着 → 先关掉，避免读到旧字数")
    closed = False
    modal = page.locator(".n-modal").first
    for sel in ("button[aria-label='close']", ".n-base-close",
                "button:has-text('取消')", "button:has-text('关闭')"):
        try:
            b = modal.locator(sel).first
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

    # 清干扰弹窗
    n = dismiss_dialogs(page, verbose=True)
    if n:
        print(f"[ai] 清掉了 {n} 个干扰弹窗")

    def _dialog_shown() -> bool:
        loc, sel = _visible(page, AI_SELECTORS["dialog"], timeout=2500)
        if loc is not None:
            print(f"[ai] ✓ 弹窗已出现: {sel}")
            return True
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


def current_model(page: Page, container: str = ".n-modal") -> str:
    """回读顶部模型选择器当前显示的名字（如「细腻版」「奇想版」）。

    ★ container：模型面板所在容器。
      - 续写：默认 ".n-modal"
      - 审稿：".n-card-content:has-text('待审文本')"
    """
    try:
        return _text_of(page.locator(f"{container} .n-base-selection"),
                        timeout=400)
    except Exception:
        return ""


def _text_of(loc, timeout: float = 300) -> str:
    """安全读文本：元素不存在时**立刻**返回空串。

    ★★ 为什么必须有这个工具（2026-10-04 实测抓到的最大性能黑洞）：
       本项目在 browser.py 里设了 `context.set_default_timeout(15000)`。
       于是 `loc.first.inner_text()`（不传 timeout）在**元素不存在**时
       不会马上失败，而是**一直等到 15 秒**才抛异常：

            locator('.__nope__').first.inner_text()          → 15009ms
            locator('.__nope__').first.inner_text(timeout=150)→   157ms
            locator('.__nope__').first.is_visible()          →     2ms

       即：**一次裸的 inner_text() 写错选择器 = 白等 15 秒**，而且是静默的
       （被 try/except 吞掉，只是"读不到"）。
       实测代价：`current_associate_level` 3 次调用 = 45.03 秒（15.01s/次）。

       所以：先 `count()`（~2ms）判断存在性，再带小超时读文本。
    """
    try:
        if not loc.count():
            return ""
        return (loc.first.inner_text(timeout=timeout) or "").strip()
    except Exception:
        return ""


def current_associate_level(page: Page) -> str:
    """回读当前「联想能力」档位（如「正常」）。读不到返回空串。

    ★★ 15 秒黑洞修复（2026-10-04 实测）：
       原实现 `page.locator("[class*=association-level]").first.inner_text()`
       **没传 timeout**。而该选择器只在**滑块浮层打开时**才存在
       （实测：浮层没开时 `count()==0`），元素不在就等到默认 15 秒。
       它在 `select_model` 里是**打开浮层之前**调用的，
       所以**每章必吃 15.0 秒**。现在改成 ~2ms 返回空串。
    """
    txt = _text_of(page.locator("[class*=association-level]"), timeout=400)
    if not txt:
        return ""
    # 形如「正常 · 0.7 | 专业 · 0.1 | …」，取第一个档位名
    first = txt.split("|")[0].strip().replace("\n", " ")
    for mark in ASSOCIATE_MARKS:
        if mark in first:
            return mark
    return ""


# 模型面板里，右栏模型卡片的「选择」按钮（实测 2026-10-03）
# 卡片本身就是一个 button，文字形如：
#   "细腻版 | 指令遵循能力强，特别听话，自己发挥少，成文质量好 | 流畅 | 选择"
# 「细腻版-O5.5」那张卡片的描述不同，用「指令遵循能力强」可精确区分。
MODEL_CARD_HINT = {
    "细腻版": "指令遵循能力强",
    # ★ 智慧版下有多张卡片（6.1S / 6A / 6S / 5.6），
    #   用卡片内的描述文字精确定位，避免选错版本。
    #   实测（2026-10-03）智慧版-6A 的卡片描述开头：
    "智慧版-6A": "更懂作者意图，能稳定抓住风格",
    "智慧版-6S": "写小说强在结构和情节",
    "智慧版-6.1S": "该模型能同时续下大纲、人物卡与多章前文",
    "智慧版-5.6": "最新的gpt-5.6模型",
}


# 联想程度滑块（实测 2026-10-03）—— 6 档，位置自动吸附
#   rail x: 358.8(专业) → 572.8(离谱)，档位名与刻度标签一一对应
ASSOCIATE_SLIDER_SEL = "[class*=association-level-slider]"
ASSOCIATE_MARKS = ["专业", "准确", "均衡", "正常", "丰富", "离谱"]


def set_associate_level(page: Page, level: str = "正常",
                        container: str = "") -> bool:
    """设置「联想能力」档位（滑块，6 档）。

    ★ 实测（2026-10-03）：模型面板左下角「联想能力」是个 button，点开后
      弹出一个浮层，里面是 Naive UI 滑块 `association-level-slider`：
          专业 · 0.1 | 准确 · 0.2 | 均衡 · 0.5 | 正常 · 0.7 | 丰富 · 1.0 | 离谱 · 1.1
      档位必须**拖手柄**（点轨道无效），拖到对应刻度 x 会自动吸附。
      浮层里还有「新手勿改」提示 —— 但用户明确要求设为「正常」。

    Args:
        level:     「专业」「准确」「均衡」「正常」「丰富」「离谱」
        container: 联想能力按钮所在容器（可选）。
                   - 续写：留空（全局文字匹配即可）
                   - 审稿：传 ".n-card-content:has-text('待审文本')"
                   注意：浮层本身是挂在 body 上的（不在 container 里），
                   所以拖拽部分始终全局找。
    """
    print(f"[ai] --- 联想能力 → {level} ---")
    if level not in ASSOCIATE_MARKS:
        print(f"[ai] ⚠ 未知档位「{level}」，用「正常」")
        level = "正常"

    # ① 点「联想能力」button 打开浮层
    sels = list(AI_SELECTORS["btn_associate"])
    if container:
        sels = [f"{container} button:has-text('联想能力')"] + sels
    if not _click_first(page, sels, label="联想能力(打开滑块)"):
        return False

    # ★ 效率改造：原来固定 sleep 0.5s 等浮层出现。
    #   改成等**滑块真的出现** —— 浮层一渲染就继续。
    sl = page.locator(ASSOCIATE_SLIDER_SEL).first
    wait_until(lambda: bool(sl.count()) and sl.is_visible(timeout=60),
               timeout=3.0, interval=0.05, desc="联想滑块浮层出现")
    if not sl.count():
        print("[ai] ✗ 浮动层里没找到联想程度滑块")
        _shot(page, "ai_assoc_slider_missing")
        return False

    # ② 找目标刻度的 x
    marks = sl.locator("[class*=n-slider-mark]")
    target_x = None
    for i in range(marks.count()):
        e = marks.nth(i)
        try:
            if _text_of(e, timeout=300) == level:
                bb = e.bounding_box()
                if bb:
                    target_x = bb["x"] + bb["width"] / 2
                    break
        except Exception:
            continue
    if target_x is None:
        # 兜底：按已知映射等比换算
        rail = sl.locator("[class*=n-slider-rail]").first
        rb = rail.bounding_box()
        idx = ASSOCIATE_MARKS.index(level)
        target_x = rb["x"] + 10 + (rb["width"] - 20) * idx / 5
    print(f"[ai] 目标刻度「{level}」x≈{target_x:.0f}")

    # ③ 拖手柄
    handle = sl.locator("[class*=n-slider-handle]").first
    hb = handle.bounding_box()
    if not hb:
        print("[ai] ✗ 拿不到滑块手柄")
        return False
    rail = sl.locator("[class*=n-slider-rail]").first
    rb = rail.bounding_box()
    y = rb["y"] + rb["height"] / 2
    try:
        page.mouse.move(hb["x"] + hb["width"] / 2, hb["y"] + hb["height"] / 2)
        page.mouse.down()
        time.sleep(0.1)
        page.mouse.move(target_x, y, steps=12)
        time.sleep(0.1)
        page.mouse.up()
    except Exception as e:
        print(f"[ai] ✗ 拖动滑块失败：{e}")
        return False

    # ★ 效率改造：原来是固定 sleep 0.4s 等吸附生效，再回读。
    #   改成**等回读文本里出现目标档位**（这本来就是 ④ 的断言条件）。
    def _assoc_readback() -> str:
        # ★ 必须带 count()+超时：浮层没开时该选择器不存在，
        #   裸 inner_text() 会等到默认 15 秒（见 _text_of 的说明）。
        return _text_of(page.locator("[class*=association-level]"),
                        timeout=400)

    wait_until(lambda: level in _assoc_readback(),
               timeout=1.5, interval=0.05, desc=f"联想能力吸附到「{level}」")

    # ④ 回读断言
    txt = _assoc_readback()
    first_line = txt.split("|")[0].strip().replace("\n", " ")
    if level in txt:
        print(f"[ai] ✓ 联想能力已设为「{level}」（当前：{first_line}）")
        ok = True
    else:
        print(f"[ai] ✗ 联想能力设置失败（当前：{first_line}）")
        ok = False

    # ⑤ 点模型面板空白处收起浮层（不要误点「使用此模型」）
    try:
        page.mouse.click(rb["x"] - 120, rb["y"] - 60)
        # ★ 等浮层真的收起（原来固定 sleep 0.3s）
        wait_gone(lambda: bool(sl.count()) and sl.is_visible(timeout=60),
                  timeout=1.0, interval=0.05, desc="联想浮层收起")
    except Exception:
        pass
    return ok


def select_model(page: Page, model: str = "细腻版",
                 associate: str = "正常",
                 container: str = ".n-modal",
                 read_container: str = "",
                 target: str = "",
                 card_hint: str = "") -> bool:
    """选模型（默认细腻版）+ 设置联想能力。

    ★ 实测（2026-10-03）—— 这是一个「两级」面板，必须按顺序走完才生效：
        ① 点顶部 `.n-base-selection` 展开面板
        ② 点左栏【分类】button（如「细腻版」）
        ③ 点右栏【模型卡片】里的「选择」（★ 关键，漏了这步等于没选）
        ④ 点底部「联想能力」→ 拖滑块到「正常」（浮层）
        ⑤ 点底部「使用此模型」
      只做 ②③ 会只切左栏高亮，顶部仍显示旧模型（如「奇想版」）。
      ★ 顺序很重要：联想能力必须在「使用此模型」之前设置。

    ★★ 容器参数化（2026-10-03 新增 / 同日修正）：
      实测确认（`_t_recon_model.py`）——**「模型选择弹窗」永远是根级
      `.n-modal.model-picker-modal`**，它跟触发它的入口（续写弹窗 /
      审稿抽屉）**完全平级**，不属于入口内部。DOM 祖先链：
        .n-modal.model-picker-modal ← .n-scrollbar-container ← body
      所以：
        - `container`（去哪点开模型选择器）——续写 / 审稿各自不同
          （续写 = 续写弹窗；审稿 = 右侧抽屉）
        - `read_container`（模型面板本体 / 回读模型名）——**恒为 `.n-modal`**
      早先误把 `container=REVIEW_PANE_SEL` 传给整个函数，导致
      `{抽屉} button:has-text('智慧版')` 找不到分类而失败。

    Args:
        model:          模型分类名，如「细腻版」「智慧版」「奇想版」
        associate:      联想能力档位：「专业」「准确」「均衡」「正常」「丰富」「离谱」
                        （传「跳过」则不调整）
        container:      ★ **去哪点开模型选择器**的容器。
                        - 续写：默认 ".n-modal"
                        - 审稿：传 ".n-card-content:has-text('待审文本')"
        read_container: ★ 模型面板本体的容器，默认跟随 container；
                        审稿传 ".n-modal"。
        target:         ★ 期望回读到的模型名（如「智慧版-6A」）。
                        留空则用 `model`。因为「分类名」和「卡片名」
                        可能不同（分类=智慧版，卡片=智慧版-6A）。
        card_hint:      ★ 覆盖 MODEL_CARD_HINT 的卡片描述文字（可选）
    """
    print(f"[ai] --- 选模型：{model} ---")
    panel = read_container or container      # 模型面板所在容器

    # ★★ 已选则跳过（2026-10-04 用户需求）：
    #   模型已经是目标（含 model/target 名），且联想能力无需改动（跳过，或
    #   当前档位已经等于目标档位）→ 不再重复打开模型面板，省掉一大段流程。
    want = target or model
    cur = current_model(page, container=panel)
    assoc_ok = (not associate or associate == "跳过")
    if not assoc_ok:
        cur_assoc = current_associate_level(page)
        # ★ 读不到档位（浮层没开）→ 假定已满足目标（站点值通常保持不变），
        #   这样「模型已对」时就能跳过，贴合「省流程」诉求；
        #   只有在**明确读到了不同档位**时才不跳过、走一遍重新设。
        assoc_ok = (cur_assoc == "" or cur_assoc == associate)
    if cur and (want in cur or cur in want) and assoc_ok:
        print(f"[ai] ✓ 模型已是「{cur}」（目标「{want}」），联想能力也满足，跳过重复选择")
        return True

    # ① 打开模型面板（★ 用 container，因为「点哪儿展开」由入口决定）
    loc = None
    for sel in AI_SELECTORS["model_selection"]:
        real = sel.replace(".n-modal", container) if ".n-modal" in sel else sel
        try:
            cand = page.locator(real).first
            if cand.is_visible(timeout=1500):
                loc = cand
                break
        except Exception:
            continue
    if loc is None:
        # 兜底：实在找不到，就在 panel 里找
        for sel in AI_SELECTORS["model_selection"]:
            real = sel.replace(".n-modal", panel) if ".n-modal" in sel else sel
            try:
                cand = page.locator(real).first
                if cand.is_visible(timeout=1500):
                    loc = cand
                    break
            except Exception:
                continue
    if loc is None:
        print("[ai] ✗ 找不到模型选择器")
        _shot(page, "ai_model_selector_missing")
        return False
    before = current_model(page, container=panel)
    print(f"[ai] 当前模型：{before or '(空)'}")

    # ★ 短超时 + JS 降级（残留遮罩会拦原生点击，长超时只会白等）
    if loc.is_visible():
        if _safe_click(loc, label="展开模型面板"):
            print("[ai] ✓ 已展开模型面板")
        else:
            print("[ai] ⚠ 展开模型面板点击失败，继续尝试")
    else:
        print("[ai] ⚠ 模型选择器不可见，尝试直接点")
        _safe_click(loc, label="展开模型面板(不可见)")

    # ★ 等根级模型弹窗出现（它是独立的，跟入口平级）
    #   ★ 效率改造：原来「点一下 → sleep 0.6 → 再轮询 12×0.4s = 最多 4.8s」，
    #     合计最多 5.4 秒。现在合并成**一次高频条件等待**：一出现就继续。
    MODEL_MODAL = ".n-modal.model-picker-modal"

    def _modal_visible() -> bool:
        try:
            m = page.locator(MODEL_MODAL).first
            return bool(m.count()) and m.is_visible(timeout=60)
        except Exception:
            return False

    opened = wait_until(_modal_visible, timeout=5.0, interval=0.05,
                        desc="模型弹窗出现").ok
    scope = MODEL_MODAL if opened else panel
    if opened:
        print("[ai] ✓ 模型弹窗已就绪（根级 .model-picker-modal）")
    else:
        print("[ai] ⚠ 没等到模型弹窗，退回原容器查找")

    # ② 点左栏分类 button（注意：分类是 button，不是 span）
    cat = page.locator(f"{scope} button").filter(has_text=model)
    picked = None
    # 优先按「模型分类」区块精确定位（左栏有自己的容器）
    try:
        in_list = page.locator(
            f"{scope} .model-picker-category-list button"
        ).filter(has_text=model)
        if in_list.count():
            picked = in_list.first
            print("[ai] （分类定位：model-picker-category-list）")
    except Exception:
        pass
    if picked is None:
        for i in range(cat.count()):
            try:
                b = cat.nth(i).bounding_box()
            except Exception:
                continue
            # 左栏分类项的 y 在面板中下部（>200），且宽度较大
            if b and b["y"] > 200 and b["width"] > 120:
                picked = cat.nth(i)
                break
    if picked is None and cat.count():
        picked = cat.first
    if picked is None:
        print(f"[ai] ✗ 模型面板里找不到分类「{model}」")
        _shot(page, "ai_model_cat_missing")
        return False
    _safe_click(picked, label=f"模型分类「{model}」")
    # ★ 效率改造：原来是固定 sleep 0.5 等右栏卡片列表刷新。
    #   改为等「分类已被选中」这一可见信号（Naive UI 会给选中项加状态类），
    #   拿不到就短暂等一下，不再无条件吃满 0.5 秒。
    wait_until(lambda: _cat_selected(picked), timeout=1.0, interval=0.05,
               desc="分类选中") or time.sleep(0.1)
    print(f"[ai] ✓ 点击 分类「{model}」")

    # ③ 点右栏模型卡片的「选择」（★ 这一步是真正选中的关键）
    hint = card_hint or MODEL_CARD_HINT.get(model, "")
    card = None
    if hint:
        c = page.locator(f"{scope} button").filter(has_text=hint)
        if c.count():
            card = c.first
    if card is None and model != target:
        # 分类名与卡片名不同（如 分类=智慧版 / 卡片=智慧版-6A）
        want_card = target or model
        c = page.locator(f"{scope} button").filter(has_text=want_card)
        if c.count():
            card = c.first
    if card is None:
        # 兜底：右栏里含模型名的卡片
        c = page.locator(f"{scope} button").filter(has_text=model)
        for i in range(c.count()):
            try:
                b = c.nth(i).bounding_box()
            except Exception:
                continue
            if b and b["x"] > 380 and b["width"] > 300:
                card = c.nth(i)
                break
    if card is not None:
        try:
            inner = card.locator("text=选择")
            _safe_click(inner.first if inner.count() else card,
                        label="模型卡片「选择」")
            print("[ai] ✓ 点击 模型卡片「选择」")
        except Exception as e:
            print(f"[ai] ⚠ 点卡片失败：{str(e).splitlines()[0]}，尝试 JS")
            try:
                card.evaluate("el => el.click()")
                print("[ai] ✓ JS 降级点击 模型卡片")
            except Exception as e2:
                print(f"[ai] ✗ 卡片点击失败：{e2}")
    else:
        print(f"[ai] ⚠ 没找到「{model}」的模型卡片，直接试用「使用此模型」")

    # ④ 联想能力（★ 必须在「使用此模型」之前）
    if associate and associate != "跳过":
        set_associate_level(page, associate, container=panel)
    else:
        print("[ai] 联想能力：跳过")

    # ⑤ 确认
    ok = False
    for sel in AI_SELECTORS["btn_use_model"]:
        real = sel.replace(".n-modal", panel) if ".n-modal" in sel else sel
        try:
            b = page.locator(real).first
            if b.count() and b.is_visible():
                ok = _safe_click(b, label="使用此模型")
                break
        except Exception:
            continue
    if not ok:
        print("[ai] ⚠ 没有「使用此模型」按钮，可能已自动选中")

    # ★ 效率改造：原来是固定 sleep 1.0 等弹窗关闭 + 模型名回读刷新。
    #   现在等**模型弹窗真的消失**（这是"确认已生效"的可见信号）；
    #   若本来就没有弹窗（回退路径），最多等 1s 就返回，不再无条件吃满。
    if opened:
        wait_gone(_modal_visible, timeout=3.0, interval=0.05,
                  desc="模型弹窗关闭")
    else:
        wait_until(lambda: not _modal_visible(), timeout=1.0, interval=0.05)
    # 再给模型名回读一点点时间（很短，通常 1~2 轮就够）
    wait_until(lambda: bool(current_model(page, container=panel)),
               timeout=0.6, interval=0.05, desc="模型名回读")

    # ⑥ ★ 回读断言（读的是入口容器，如审稿抽屉里的模型名）
    #
    # ★ 放宽说明（2026-10-03 实测）：
    #   审稿抽屉的「AI模型」下拉在**生成前**有时读出来是空串
    #   （DOM 里 .n-base-selection 还没渲染文字），但模型其实已经选上了
    #   —— 事后从卡片 innerText 能看到「模型: 智慧版-6A」。
    #   所以：**读不到（空）不当失败**，只要过程中的「卡片点击」步骤
    #   走通了（card is not None）就算成功。这避免误报
    #   「ai_model_switch_failed」截图噪音。
    after = current_model(page, container=panel)
    want = target or model
    if after and (want in after or after in want):
        print(f"[ai] ✓ 模型已切换为「{after}」")
        return True
    if not after:
        # 读不到 → 不判失败（可能只是没渲染出去），但把证据记一下
        print(f"[ai] ⚠ 回读为空（面板未渲染模型名），"
              f"按流程判定已选「{want}」")
        return card is not None
    print(f"[ai] ✗ 模型没切成功：仍显示「{after or '(空)'}」（目标「{want}」）")
    _shot(page, "ai_model_switch_failed")
    return False


def fill_plot(page: Page, text: str) -> bool:
    """填写「后续剧情」。

    ★ 效率改造（2026-10-04 实测）：原来是「fill 完固定 sleep 0.8s」。
      实测 fill 本身只要几十毫秒，那 0.8 秒是纯白等（每章都吃）。
      现在改成**回读 textarea 内容**确认 —— 通常 1~2 次轮询就成立。
      ★ 回读结果**不参与成败**：读不到文本时只提示一行日志，仍然返回 True
        （与原实现一致），避免站点改渲染方式时误报失败。
    """
    print(f"[ai] --- 填写后续剧情（{len(text)} 字）---")
    ok = _fill_first(page, AI_SELECTORS["plot_input"], text, label="后续剧情")
    if not ok:
        return False

    probe = text.strip()[:24]

    def _filled() -> bool:
        if not probe:
            return True
        try:
            loc = page.locator(AI_SELECTORS["plot_input"][0]).first
            if not loc.count():
                return False
            return probe in (loc.input_value(timeout=300) or "")
        except Exception:
            return False

    if not wait_until(_filled, timeout=1.0, interval=0.05,
                      desc="剧情已填入").ok:
        print("[ai]   （未能回读到剧情文本，继续；不影响成败判定）")
    return True


# ---------------------------------------------------------------- 快捷选项
#
# ★ 实测（2026-10-03）「快捷选项」这一行（红框那一行）：
#
#   它是个 **Naive UI 的 n-select**，但点它 **不弹下拉菜单**，
#   而是弹出一个**全屏 modal**（`.shortcut-picker-modal`），里面：
#     - 左栏「已收藏」：一行一个 `.prompt-row`（含 `.row-title` 文字）
#     - 右栏「最新」  ：同样是 `.prompt-row`
#     - 底部：创建 / 编辑 / 更多提示词
#
#   点中某一行 `.prompt-row` → 面板自动关闭 → 顶部那一行变成该提示词的名字。
#
#   ★ 通用定位方式（不受列表顺序、收藏变动影响）：
#       `.shortcut-picker-modal .prompt-row:has-text('关键词')`
#   即 **用文字定位**，而不是记第几行。
#
#   额外兜底：
#     - 面板里可以先用搜索框搜关键词，缩小列表再点
#     - 文字可能被站点改写（如「云哥/云霄」「逆袭/逆徒」），
#       所以支持**模糊关键词**（取几个稳定的字即可）

def current_shortcut(page: Page) -> str:
    """回读「快捷选项」那一行当前显示的提示词名字。"""
    return _text_of(page.locator(AI_SELECTORS["shortcut_row"][0]),
                    timeout=400)


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
                         poll: float = 0.1) -> int:
    """★ 等「快捷选项」面板把提示词列表加载出来。

    ★ 实测坑（2026-10-03）：面板打开瞬间是**空的**，显示
      「已收藏 0」「正在加载收藏提示词…」，
      要等 2~6 秒才渲染出 28+ 条。
      不等的话 `pick_shortcut` 会看到 0 项 → 直接判「没有含关键词的提示词」
      → **明明有这个提示词却选不上**。

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
    wait_shortcut_loaded(page)

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

    if keyword:
        # 优先：整串关键词
        m = rows.filter(has_text=keyword)
        n = m.count()
        if n:
            if index < n:
                target = m.nth(index)
                matched_by = f"has-text({keyword!r})"
            else:
                target = m.first
                matched_by = f"has-text({keyword!r}) first"

        # 兜底：把关键词切成 2 字片段逐个试（应对站点改字，如 云霄/云哥）
        # ★ 但只认「片段命中数唯一」的情况，避免选错
        if target is None and len(keyword) >= 4:
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
                target = cands[0][1]
                matched_by = f"片段 {cands[0][0]!r}（唯一命中）"
            elif len(cands) > 1:
                # 多个片段各自唯一命中，取第一个但打日志提示
                target = cands[0][1]
                matched_by = (f"片段 {cands[0][0]!r}"
                              f"（注意：{len(cands)} 个片段都能命中）")

    if target is None:
        # ★ 有关键词却没命中 → 不选错，但也**不阻断主流程**
        #   （用户要求：有则改、没有就跳过，不影响进程）
        if keyword:
            n = rows.count()
            print(f"[ai] ⚠ 面板里没有含「{keyword}」的提示词（共 {n} 项）"
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

    ok_click = False
    try:
        target.click(timeout=CLICK_FAST_TIMEOUT)
        ok_click = True
    except Exception as e:
        print(f"[ai] ⚠ 常规点击失败：{str(e).splitlines()[0]}")
        try:
            # 退化为点行内标题
            t = target.locator(".row-title").first
            if t.count():
                t.click(timeout=3000)
                ok_click = True
        except Exception:
            pass
        if not ok_click:
            try:
                target.click(force=True, timeout=3000)
                ok_click = True
            except Exception as e2:
                print(f"[ai] ✗ 点不动这一行：{str(e2).splitlines()[0]}")

    if not ok_click:
        _shot(page, "ai_shortcut_click_failed")
        return False

    # ★ 效率改造：原来是固定 sleep 1.2s 等面板收起 + 那一行刷新。
    #   现在等**面板收起**这一可见信号；面板若本来就关了则立刻返回。
    #   ★ 注意：这里的等待结果**故意不作为成败判据**（成败已由 ok_click
    #     决定），所以即使站点某些版本不自动关面板，也只会多等 1.5 秒，
    #     不会被误判成失败 —— 行为上是安全的降级。
    wait_gone(
        lambda: any(page.locator(s).first.is_visible(timeout=60)
                    for s in AI_SELECTORS["shortcut_panel"]
                    if page.locator(s).count()),
        timeout=1.5, interval=0.05, desc="快捷选项面板收起")
    if verify_row:
        wait_until(lambda: bool(current_shortcut(page)),
                   timeout=1.0, interval=0.06, desc="快捷选项行刷新")

    # ⑤ 回读断言：必须跟「点中的那一行」对得上才算成功
    #   ★ verify_row=False 用于「审稿要求」场景——那边点中的面板没错，
    #     但「那一行」不是续写弹窗的 shortcut_row，回读必然为空（噪音）。
    if not verify_row:
        if ok_click:
            print("[ai] ✓ 已点中目标提示词（跳过行回读）")
        return ok_click

    after = current_shortcut(page)
    print(f"[ai] 选择后那一行显示：{after!r}")
    if not after:
        print("[ai] ✗ 回读不到快捷选项（可能没切成功）")
        _shot(page, "ai_shortcut_switch_failed")
        return False

    # 点中行的标题（去掉「使用方法」等尾巴）
    want = txt.split("使用方法")[0].strip()
    want_core = want.split("（")[0].strip()          # 去掉（细腻优先…）
    after_core = after.split("（")[0].strip()

    hit = False
    if keyword and (keyword in after):
        hit = True
    elif want and (want == after or want_core == after_core):
        hit = True
    elif want_core and len(want_core) >= 4 and want_core[:8] in after:
        hit = True

    if hit:
        print("[ai] ✓ 快捷键选项已切换")
        return True

    print(f"[ai] ✗ 点了「{want[:30]}」但当前显示「{after[:30]}」，没对上")
    _shot(page, "ai_shortcut_switch_failed")
    return False


# ---------------------------------------------------------------- 关联章节
#
# ★★ 真实 DOM 结构（2026-10-04 现场抓取，不再靠猜）：
#   「关联章节」那一行的按钮组按顺序是：
#
#       [清空] [最近3章] [最近N章 ⌄] [选择章节]
#                       ↑ 当前档位就写在按钮文字上
#
#   - 「最近3章」是**普通按钮**：class 里没有 `overflow-hidden`，svg 数 = 0
#   - 「最近N章 ⌄」是**下拉按钮**：class 末尾是 `px-0 overflow-hidden`，svg 数 = 1；
#     它的文字就是**当前档位**（默认「最近5章」，选了 10 就变成「最近10章」）。
#     实测 class：
#       n-button n-button--primary-type n-button--medium-type
#       n-button--secondary px-0 overflow-hidden
#   - 菜单是 teleport 出去的浮层，选项为「最近5章 / 最近8章 / 最近10章」；
#     ★ 菜单**收起时这些文字根本不在 DOM 里**（实测"含最近"的浮层查询为空）。
#
# ★★ 旧实现的致命 bug（2026-10-04 实测复现，这是"第2章之后静默失效"的根因）：
#   旧代码用 `.n-modal button` 过滤 `has_text="最近5章"` 去定位按钮组。
#   可那个文字**只在当前档位正好是 5 章时才存在**，于是：
#     - 会话里第一次跑（默认 5 章）→ 侥幸命中，看起来正常
#     - 之后每一章（按钮已变成「最近10章」）→ 找不到 →
#       白等 2s + 4s = 6 秒 → 返回 False
#   而调用方（ai_continue / ai_batch_chapters）**拿到 False 也不中断**，
#   于是第 2 章起**静默丢失「关联章节」**：模型看不到前文 → 内容质量下滑，
#   日志里只有一行 `✗ 找不到章节数按钮组`。这是**内容质量事故**，不是慢一点。
#   另外旧实现结尾用 `wait_gone(text=最近10章)` 等菜单收起 —— 选完之后
#   **按钮自己的文字就是「最近10章」**，所以这个等待**每次必定超时 3 秒**。
#
# → 现在：靠 class（overflow-hidden）定位下拉按钮、靠**回读按钮文字**判定成败、
#   并且**已经是目标档位就直接跳过**（0 次点击、0 秒等待）。

RELATE_DROPDOWN_SEL = ".n-modal button.overflow-hidden"


def _relate_dropdown(page: Page):
    """定位「最近N章 ⌄」下拉按钮（找不到返回 None）。只读，不点击。"""
    # 主路径：Tailwind 的 overflow-hidden 类把下拉按钮和「最近3章」区分开
    try:
        cands = page.locator(RELATE_DROPDOWN_SEL).filter(
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
        allb = page.locator(".n-modal button")
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


def relate_chapters(page: Page, count: int = 10, force: bool = False) -> bool:
    """关联最近 N 章。

    流程：定位「最近N章 ⌄」按钮 → （已是目标档就跳过）→ 点箭头展开菜单
          → 点「最近{count}章」→ **回读按钮文字**确认生效。

    Args:
        count: 目标档位（3 / 5 / 8 / 10 …）
        force: 即使已经是目标档也重设一遍（默认 False）

    ★ 效率（2026-10-04 实测口径）：已是对应档位时 **0 秒 0 点击**；
      需要切换时约 0.3~0.6 秒（原来固定 6.2 秒，且第 2 章起必失败）。
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
    cur = current_relate_count(page)
    if cur == count and not force:
        print(f"[ai] ✓ 关联章节已是「最近{count}章」，跳过（0 点击）")
        return True

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
    res = wait_until(lambda: current_relate_count(page) == count,
                     timeout=3.0, interval=0.08,
                     desc=f"档位回读=最近{count}章")
    if res.ok:
        print(f"[ai] ✓ 已选「最近{count}章」（回读确认，{res.elapsed:.2f}s）")
        return True

    now = current_relate_count(page)
    print(f"[ai] ✗ 点了「最近{count}章」但档位没生效（当前 "
          f"{'最近%d章' % now if now > 0 else '读不到'}）")
    _shot(page, "ai_count_option_missing")
    return False


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
    """
    try:
        modal = page.locator(".n-modal").first
        if not modal.count():
            modal = page.locator(".n-card").first
        if not modal.count():
            return False
        return bool(modal.locator("button:has-text('重新生成')").count()
                    and modal.locator("button:has-text('采纳使用')").count())
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


# ================================================================ AI 审稿
#
# ★ 实测（2026-10-03）——「AI审稿」跟「AI续写正文」**完全不是一个东西**：
#
#   ┌────────────┬──────────────────────┬──────────────────────────┐
#   │            │ AI续写正文            │ AI审稿                    │
#   ├────────────┼──────────────────────┼──────────────────────────┤
#   │ 承载形式    │ 居中弹窗 .n-modal     │ **右侧抽屉面板**          │
#   │ 定位方式    │ .n-modal:has-text(…)  │ .n-card-content:has-text(…)│
#   │ 主要输入    │ 后续剧情 textarea     │ **待审文本** textarea     │
#   │ 提示词入口  │ 续写要求（n-select）   │ **审稿要求**（3 个 tab）  │
#   │ 开始按钮    │ 开始 AI 续写           │ **生成**                  │
#   └────────────┴──────────────────────┴──────────────────────────┘
#
#   ★ 三大坑（都是实测踩出来的）：
#
#   1. **面板不是 modal** —— `.n-modal` / `[role=dialog]` 全部抓不到。
#      容器类名 `chapter-side-pane-c` 是**动态生成**的，
#      所以唯一稳定锚点是**文字**：`.n-card-content:has-text('待审文本')`。
#
#   2. **「审稿要求」是三个 tab**（快捷选项 / 自定义 / 更多），
#      点「快捷选项」才出现那一行下拉（第 2 个 .n-base-selection）。
#      实测「快捷选项」和「更多」**同时带 --checked**（Naive UI 的样式怪癖），
#      所以不能用 class 判断，只能**按文字点**。
#
#   3. **待审文本会自动带入当前章内容**（打开面板就有），
#      一般不用手动填；需要指定时再覆盖。
#
#   ★ 模型面板在抽屉里是**同一套两级结构**，可以复用 select_model()，
#     只把 container 换成抽屉选择器即可（见 select_model 的 container 参数）。
# ================================================================

REVIEW_PANE_SEL_DEFINED = True  # （锚点常量已上移到文件头部）


def open_review_pane(page: Page, wait: float = 0.6,
                     max_try: int = 4) -> bool:
    """点顶部「AI审稿」，等右侧抽屉面板出现。

    ★ 实测坑：跟续写一样，打开作品后常有干扰弹窗
      （「是否默认打开上次章节？」「国庆特惠」通知）挡住工具栏，
      导致点击超时或点了没反应。

    ★ 策略（重要）：**重试 + 柔性**
      - 每次先「清干扰」（有则关、没有就跳过，绝不阻塞）
      - 点击后轮询等面板；没出来就再来一轮
      - 全程不抛异常

    Args:
        wait:    点击后等待秒数
        max_try: 最多尝试几次
    """
    print("[ai] --- 打开「AI审稿」面板 ---")

    for attempt in range(1, max_try + 1):
        # ① 清干扰（有则关、没则跳过）
        try:
            n = dismiss_dialogs(page, verbose=(attempt == 1))
            if n and attempt > 1:
                print(f"[ai] 清掉了 {n} 个干扰弹窗")
        except Exception:
            pass

        if review_pane_open(page):
            print("[ai] ✓ 审稿面板已在")
            return True

        # ② 点「AI审稿」
        try:
            btn = page.locator(AI_SELECTORS["btn_review"][0]).first
            if btn.count():
                try:
                    btn.scroll_into_view_if_needed(timeout=CLICK_FAST_TIMEOUT)
                except Exception:
                    pass
                # ★ 短超时原生点击 + JS 降级（站点残留遮罩会拦原生点击，
                #   详见 CLICK_FAST_TIMEOUT 处说明）
                try:
                    btn.click(timeout=CLICK_FAST_TIMEOUT)
                    print(f"[ai] ✓ 已点「AI审稿」（第 {attempt} 次）")
                except Exception:
                    btn.evaluate("e => e.click()")
                    print(f"[ai] ✓ 已点「AI审稿」（第 {attempt} 次，JS 降级）")
            else:
                print(f"[ai] ⚠ 第 {attempt} 次：找不到「AI审稿」按钮")
        except Exception as e:
            print(f"[ai] ⚠ 第 {attempt} 次点击失败：{str(e).splitlines()[0]}")

        # ③ 等面板
        #   ★ 效率改造（2026-10-04 实测）：原来是「固定 sleep(wait=0.6)
        #     + 最多 8 次 × sleep(0.5)」→ 最快 1.1 秒才返回、最坏 4.6 秒。
        #     现在是一次条件等待：面板一出现就继续。
        #   ★★ 谓词必须是 lambda：`review_pane_open` 需要 page 参数。
        #     写成 `wait_until(review_pane_open, ...)` 会每轮抛 TypeError
        #     被吞掉 → 必然超时 7.6 秒，再白重做一轮点击+清干扰
        #     （实测每章白等 8.5 秒；而面板其实 0.3 秒就出来了）。
        if wait_until(lambda: review_pane_open(page),
                      timeout=max(float(wait), 0.6) + 3.0,
                      interval=0.08, desc="审稿面板出现").ok:
            print("[ai] ✓ 审稿面板已出现")
            return True
        print("[ai]   面板未出现，重试…")

    print("[ai] ✗ 审稿面板打不开")
    _shot(page, "ai_review_pane_missing")
    return False


def review_pane_open(page: Page) -> bool:
    """审稿面板是否已打开（★ 用文字锚点，不依赖动态类名）。"""
    try:
        loc = page.locator(REVIEW_PANE_SEL)
        return bool(loc.count() and loc.first.is_visible())
    except Exception:
        return False


def close_review_pane(page: Page, wait: float = 1.0, max_try: int = 3) -> bool:
    """关闭右侧「AI审稿」抽屉。

    ★ 为什么要这个：一条龙终局时审稿抽屉是**开着的**，
      它盖住右半边，会导致后续读正文/点击图到错元素
      （2026-10-03 E2E 结论段读到 216 字就是这个原因）。

    策略（有则关、没则跳过，不抛异常）：
      ① 抽屉自己的关闭按钮 `button[aria-label='close']`
      ② `button[aria-label='close'].n-base-close.n-card-header__close`
      ③ ESC
      ④ 点遮罩 `.n-modal-mask` / 抽屉外部
    """
    if not review_pane_open(page):
        print("[ai] 审稿抽屉未开，无需关闭")
        return True
    print("[ai] --- 关闭审稿抽屉 ---")
    for _ in range(1, max_try + 1):
        # ① / ② 关闭按钮
        for sel in [
            ".n-card-header button[aria-label='close']",
            "button[aria-label='close'].n-card-header__close",
            ".n-card-header .n-base-close",
            ".n-drawer button[aria-label='close']",
            ".n-drawer .n-base-close",
            "button[aria-label='close']",
        ]:
            try:
                loc = page.locator(sel)
                n = loc.count()
                for i in range(min(n, 6)):
                    b = loc.nth(i)
                    try:
                        if not b.is_visible():
                            continue
                        _safe_click(b, label="关闭审稿抽屉")
                    except Exception:
                        continue
                    # ★ 条件等待抽屉关掉（原来固定 sleep(wait)=1.0s）
                    if wait_gone(lambda: review_pane_open(page),
                                 timeout=max(float(wait), 1.0),
                                 interval=0.05, desc="审稿抽屉关闭").ok:
                        print(f"[ai] ✓ 已关闭审稿抽屉（点 {sel}）")
                        return True
            except Exception:
                continue
        # ③ ESC
        try:
            page.keyboard.press("Escape")
            if wait_gone(lambda: review_pane_open(page),
                         timeout=max(float(wait), 1.0),
                         interval=0.05, desc="审稿抽屉关闭").ok:
                print("[ai] ✓ 已关闭审稿抽屉（ESC）")
                return True
        except Exception:
            pass
        # ④ 点遮罩 / 空白处
        try:
            for sel in [".n-modal-mask", ".n-drawer-mask", "body"]:
                m = page.locator(sel).first
                if m.count():
                    m.click(position={"x": 8, "y": 8},
                            timeout=CLICK_FAST_TIMEOUT)
                    if wait_gone(lambda: review_pane_open(page),
                                 timeout=max(float(wait), 1.0),
                                 interval=0.05, desc="审稿抽屉关闭").ok:
                        print(f"[ai] ✓ 已关闭审稿抽屉（点 {sel}）")
                        return True
        except Exception:
            pass
    print("[ai] ⚠ 审稿抽屉仍未关（继续，不阻断）")
    return not review_pane_open(page)


def current_review_requirement(page: Page) -> str:
    """回读「审稿要求」那一行当前显示的提示词名。"""
    try:
        sels = page.locator(AI_SELECTORS["review_selects"][0])
        if sels.count() >= 2:
            return _text_of(sels.nth(1), timeout=400)
    except Exception:
        pass
    return ""


def fill_review_text(page: Page, text: str = "",
                     instruction: str = "",
                     read_body: bool = True) -> bool:
    """填写「待审文本」。

    ★ 实测：打开面板时**已自动带入当前章正文**。

    ★★ 用户需求（2026-10-03）：待审文本是**自带章节正文的**，
      但希望在正文基础上**再追加一段指令**（类似「指令模板」的写法），
      比如：

          请按爽文节奏审改以下正文，重点检查毒点与逻辑断裂。
          ——以下为正文——
          （这里是章节原文…）

      所以设计成：
        - `instruction` 非空 → **正文 + 分隔 + 指令** 拼起来整段填进去
        - `text` 非空        → 直接用它（完全覆盖，不管正文）
        - 两个都空           → 沿用页面自带内容（不动）

    Args:
        text:        显式待审文本；给了就完全覆盖（优先级最高）
        instruction: ★ 指令模板/要求，会跟当前章正文拼在一起
        read_body:   instruction 模式下是否去读当前章正文来拼
                     （False = 只填指令）

    Returns:
        bool 是否成功
    """
    def _settle(expected: str) -> None:
        """★ 等填进去的内容真的在 textarea 里（替代固定 sleep 0.8s）。

        原来填完固定等 0.8 秒就返回，其实内容早就写好了；
        改成回读确认（顺带能发现"填了但没生效"的情况），通常几十毫秒。
        """
        tail = expected.strip()[-40:] if expected.strip() else ""
        if not tail:
            return
        wait_until(
            lambda: any(
                tail in (page.locator(s).first.input_value() or "")
                for s in AI_SELECTORS["review_text"]
                if page.locator(s).count()),
            timeout=2.0, interval=0.06, desc="待审文本落盘")

    # ① 显式 text → 直接覆盖
    if text:
        print(f"[ai] --- 填写待审文本（显式 {len(text)} 字）---")
        ok = _fill_first(page, AI_SELECTORS["review_text"], text,
                         label="待审文本")
        _settle(text)
        return ok

    # ② 正文 + 指令 拼接
    if instruction:
        body = get_body_text(page) if read_body else ""
        if body:
            full = (f"{instruction.strip()}\n\n"
                    f"————————以下为待审正文————————\n\n{body}")
            print(f"[ai] --- 待审文本 = 指令({len(instruction)}字) "
                  f"+ 正文({len(body)}字) = {len(full)} 字 ---")
        else:
            full = instruction.strip()
            print(f"[ai] --- 待审文本 = 仅指令（{len(full)} 字，"
                  f"没读到正文）---")
        ok = _fill_first(page, AI_SELECTORS["review_text"], full,
                         label="待审文本")
        _settle(full)
        return ok

    # ③ 都空 → 不动（沿用页面自带当前章内容）
    print("[ai] 待审文本：留空，沿用页面自带内容")
    return True


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

    # ① 点 tab（★ 按文字点，不用 class：快捷选项/更多会同时带 --checked）
    #    ★ 实测：`{面板} .n-radio-button:has-text(...)` 常点击超时，
    #      因为 tab 在抽屉内但可能有遮挡/动画。改为 JS 精确定位 + 原生点击。
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

    # ★ 效率改造：原来切 tab 后固定 sleep 0.5s。
    #   改成等**下拉行真的渲染出来**（tab 切换生效的可见信号）：
    #   2 个 .n-base-selection 都出现即可。找不到也无妨（下面有判空）。
    wait_until(lambda: page.locator(
        AI_SELECTORS["review_selects"][0]).count() >= 2,
        timeout=2.0, interval=0.05, desc="审稿要求行就绪")

    if not keyword:
        return True

    # ② 点那一行下拉（★ 第 2 个 .n-base-selection）
    try:
        sels = page.locator(AI_SELECTORS["review_selects"][0])
        if sels.count() < 2:
            print("[ai] ✗ 找不到「审稿要求」那一行下拉")
            _shot(page, "ai_review_req_row_missing")
            return False
        row = sels.nth(1)
        # 已经是目标了 → 跳过（回读断言，避免白点）
        cur = _text_of(row, timeout=400)
        if keyword and keyword in cur:
            print(f"[ai] 审稿要求已是「{cur[:40]}」，跳过")
            return True
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
        return False

    # ③ 用文字定位选提示词（复用续写的逻辑；★ 不回读续写那一行）
    ok = pick_shortcut(page, keyword=keyword, panel_already_open=True,
                       verify_row=False)
    # ★ 效率改造：原来固定 sleep 0.5s 等那一行刷新。改成等回读出现关键词。
    #   超时从 2.0 降到 1.0：回读本身只是读一次文本，真的成功会立刻命中；
    #   1 秒还没命中就说明这一步没生效，再等也没用（原来 2 秒纯属白等）。
    wait_until(lambda: keyword in (current_review_requirement(page) or ""),
               timeout=1.0, interval=0.06, desc="审稿要求行刷新")

    # ④ 回读断言
    after = current_review_requirement(page)
    if after and (keyword in after):
        print(f"[ai] ✓ 审稿要求已切换：{after[:50]}")
        return True
    print(f"[ai] ⚠ 审稿要求回读：「{after[:50]}」（目标含「{keyword}」）")
    return ok


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


# ---------------------------------------------------------------- 正文编辑器
#
# ★ 实测（2026-10-03）—— 审稿的两个前置条件，缺一不可：
#     ① 必须先**打开一个章节**（不打开的话正文区是空的，待审文本也是空的）
#     ② 生成完成后要**先全选正文**再点「替换 / 插入」，
#        否则会在光标处**插入**（原文还在，变成前后拼接）；
#        选中之后才会**替换**掉原文。
#
#   编辑器正文 = `.tiptap.ProseMirror`
#   全选按钮   = `button[aria-label='全选']`（★ aria-label 不是 title）

def editor_ready(page: Page,
                 need_text: bool = False) -> bool:
    """正文编辑器是否已就绪（有 .tiptap.ProseMirror 且可见）。

    Args:
        need_text: ★ True 时要求**正文非空**才算就绪。
                   实测（2026-10-03）：进编辑器后 `.tiptap.ProseMirror`
                   **一直存在**（空壳），所以只判存在会误判「已就绪」，
                   结果待审文本是空的。需要「真有内容」的场景要传 True。
    """
    for sel in AI_SELECTORS["editor_body"]:
        try:
            loc = page.locator(sel).first
            if not (loc.count() and loc.is_visible()):
                continue
            if need_text and not get_body_text(page).strip():
                continue
            return True
        except Exception:
            continue
    return False


def get_body_text(page: Page) -> str:
    """读正文编辑器里的纯文本。"""
    try:
        return page.evaluate("""() => {
          const ed = document.querySelector('.tiptap.ProseMirror')
                     || document.querySelector("div[contenteditable='true']");
          return ed ? (ed.innerText || '') : '';
        }""") or ""
    except Exception:
        return ""


def chapter_items(page: Page):
    """定位左栏章节项（★ 用**容器** `.chapter-item`，不是标题 h3）。

    实测（2026-10-03）左栏 DOM：
        <div class="chapter-item chapter-item--active ...">
          <h3 class="chapter-item__title">第2章</h3>
          <span class="chapter-item__meta">104 字</span>
          ...
          <div class="chapter-item__hover-actions ...">… 生成</div>
        </div>
    ★ 坑1：`h3.chapter-item__title` 也能点，但**容器**更稳（标题很窄，36px）。
    ★ 坑2：容器里有个「生成」按钮，直接点容器别去点那个按钮。
    ★ 坑3：`chapter-item--active` 表示已打开。已打开的章节点它没用，
           要确认编辑器里真有内容（见 `editor_ready`）。
    """
    for sel in AI_SELECTORS["chapter_item"]:
        try:
            loc = page.locator(sel)
            if loc.count():
                return loc
        except Exception:
            continue
    return page.locator(".chapter-item")


def open_chapter(page: Page, which: str = "", index: int = 0,
                 wait: float = 2.5) -> bool:
    """打开章节列表里的某一章（★ 审稿前必须做，否则正文是空的）。

    Args:
        which: 章节标题关键词（如「第2章」）；留空则按 index 选
        index: which 为空时选第几个章节项（从 0 开始）
        wait:  点完之后等多久（等正文渲染）

    ★ 为什么要这步：进作品编辑器后**可能不会自动打开任何章节**。
      实测：`editor_ready()` 会因为 `.tiptap.ProseMirror` 存在而返回 True，
      但里面**一个字都没有**（正文区是空壳），需要真的点开一章。

    ★★ 踩坑（2026-10-03 实测）：
       1) 必须先 `dismiss_dialogs()`——「是否默认打开上次章节？」是居中模态，
          **会截获所有点击**，导致 `Locator.click: Timeout 4000ms exceeded`。
       2) 点**容器** `.chapter-item`，不要点 h3 标题（标题只有 36px 宽）。
       3) 点完要校验正文**非空**，光看 `editor_ready` 不算数。
    """
    # ⓪ ★ 先清弹窗（否则点击被拦截）
    dismiss_dialogs(page, verbose=False)

    body_now = get_body_text(page)
    if body_now and not which:
        print(f"[ai] 正文已有内容（{len(body_now)} 字），跳过打开章节")
        return True

    print(f"[ai] --- 打开章节（{which or f'第{index}个'}）---")
    items = chapter_items(page)
    n = items.count()
    if not n:
        print("[ai] ✗ 左栏没有章节项")
        _shot(page, "ai_open_chapter_failed")
        return False
    print(f"[ai]   左栏共 {n} 个章节")

    if which:
        target_i = None
        for i in range(n):
            try:
                t = _text_of(items.nth(i), timeout=400)
            except Exception:
                t = ""
            if which in t:
                target_i = i
                break
        if target_i is None:
            # ★ 根因修复（2026-10-03）：之前退回「第 index 个」（倒序列表第0个=最新章），
            #   会把内容写进错误的章节。现在退回「第1章（最小章号）」，并醒目警告。
            nos = chapter_numbers(page)
            first_no = min(nos) if nos else 1
            print(f"[ai] ⚠ 没找到含「{which}」的章节！退回第{first_no}章"
                  f"（而不是最新章，避免写错章节）")
            # 找到最小章号对应的下标
            target_i = 0
            for i in range(n):
                try:
                    t = _text_of(items.nth(i), timeout=400)
                except Exception:
                    t = ""
                if f"第{first_no}章" in t:
                    target_i = i
                    break
    else:
        target_i = min(index, n - 1)

    el = items.nth(target_i)
    # ★ 记下点击前的正文，用来判断"真的换章了"
    body_before = get_body_text(page)
    try:
        el.click(timeout=CLICK_FAST_TIMEOUT)
    except Exception as e:
        print(f"[ai] ⚠ 常规点击失败（{str(e).splitlines()[0]}），试 JS 点击")
        try:
            el.evaluate("e => e.click()")
        except Exception as e2:
            print(f"[ai] ✗ JS 点击也失败：{str(e2).splitlines()[0]}")
            _shot(page, "ai_open_chapter_failed")
            return False

    # 等正文渲染出来。
    # ★ 效率+正确性改造（2026-10-04 实测）：
    #   原实现是「先固定 sleep 0.7s，再看正文非空」——
    #     · 白等：正文通常 ~100ms 就渲染好了，那 0.7 秒纯属浪费（每章都吃）
    #     · 而且**判据不够严**：切章瞬间编辑器里还留着**上一章**的正文，
    #       "非空"会立刻成立 → 可能读到旧章内容（静默错章）。
    #   现在：轮询"正文非空 **且** 与点击前不同"，既快又更可靠。
    #     （点击前本来就是空章时，只要非空即算成功。）
    def _switched() -> bool:
        t = get_body_text(page)
        if not t.strip():
            return False
        return (not body_before.strip()) or (t != body_before)

    res = wait_until(_switched, timeout=max(wait, 2.0) * 2,
                     interval=0.08, desc="章节正文渲染")
    if res.ok:
        print(f"[ai] ✓ 已打开章节（正文 {len(get_body_text(page))} 字，"
              f"{res.elapsed:.2f}s）")
        return True
    print("[ai] ⚠ 点了章节但正文还是空的（可能是空章）")
    _shot(page, "ai_open_chapter_empty")
    return False


def select_all_body(page: Page, verify: bool = True) -> bool:
    """★ 全选正文编辑器里的内容。

    ★ 为什么必须全选（用户要求）：
        审稿生成的「替换 / 插入」是**智能双模**——
          有选中 → **替换**选中内容
          没选中 → 光标处**插入**
        不全选的话，结果会**插在原稿前面**，原稿还留着（前后拼接）。

    ★ 实测两条路都行（都能选中 106 字全文）：
        ① 点工具栏 `button[aria-label='全选']`  ← 首选
        ② 编辑器聚焦后 `Ctrl+A`                ← 兜底

    Args:
        verify: 是否校验选区（True 时读 selection 长度）
    """
    print("[ai] --- 全选正文 ---")

    def _selected(timeout: float) -> bool:
        """★ 条件等待「选区真的出现」，替代原来的固定 sleep 0.8s。

        选区是浏览器**瞬时**状态，点完立刻就能读到；原来固定等 0.8 秒
        纯属白等。这里高频轮询，通常 1~2 次就返回。
        """
        if not verify:
            # 不校验时也要给一点点时间让点击生效（避免紧接着的替换读到旧选区）
            time.sleep(0.15)
            return True
        return wait_until(lambda: _selection_len(page) > 0,
                          timeout=timeout, interval=0.05,
                          desc="全选生效").ok

    # ① 点「全选」按钮（aria-label，★ 不是 title！踩过坑）
    for sel in AI_SELECTORS["btn_editor_select_all"]:
        try:
            b = page.locator(sel).first
            if b.count() and b.is_visible():
                # ★ 短超时 + JS 降级：残留遮罩会让原生点击白等满 4 秒
                #   （实测该步骤 4.21 秒/章，改完约 0.1 秒）
                _safe_click(b, label="全选")
                if _selected(2.5):
                    print(f"[ai] ✓ 已全选（按钮 {sel}）")
                    return True
                print("[ai] ⚠ 点了「全选」但没选中，试 Ctrl+A")
                break
        except Exception as e:
            print(f"[ai] ⚠ 点「全选」失败：{str(e).splitlines()[0]}")
            continue

    # ② 兜底：聚焦编辑器 + Ctrl+A
    try:
        page.evaluate("""() => {
          const ed = document.querySelector('.tiptap.ProseMirror')
                     || document.querySelector("div[contenteditable='true']");
          if (ed) { ed.focus(); }
        }""")
        # 等编辑器真的拿到焦点（原来是固定 sleep 0.3）
        wait_until(lambda: page.evaluate(
            "() => !!document.activeElement && "
            "(document.activeElement.isContentEditable "
            "|| document.activeElement.tagName === 'DIV')"),
            timeout=1.5, interval=0.05, desc="编辑器聚焦")
        page.keyboard.press("Control+a")
        if _selected(2.0):
            n = _selection_len(page)
            print(f"[ai] ✓ 已全选（Ctrl+A，选区 {n} 字）")
            return True
        print("[ai] ✗ Ctrl+A 也没选中")
    except Exception as e:
        print(f"[ai] ✗ Ctrl+A 失败：{str(e).splitlines()[0]}")

    _shot(page, "ai_select_all_failed")
    return False


def _selection_len(page: Page) -> int:
    """当前选区长度（字符数）。"""
    try:
        return int(page.evaluate(
            "() => { const s = window.getSelection();"
            " return s ? s.toString().length : 0; }") or 0)
    except Exception:
        return 0


# ---------------------------------------------------------------- 审稿结果落盘

# ★ 审稿生成完成后的「替换 / 插入」按钮。实测（2026-10-03 截图）：
#   抽屉底部按钮栏（两排）：
#     上排：继续追问 | ← 上一步
#     下排：🔄重新生成 | 复制 | 对比
#     最下：导出至作品 | 🟢替换 / 插入
#   → 「替换 / 插入」是**绿色（success 型）**，文字含空格和斜杠。
REVIEW_RESULT_TEXT = "替换"


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

    # ① 点击：优先用「类名 + 位置」精确点（比文字更稳）
    clicked = False
    for sel in AI_SELECTORS["btn_review_replace"]:
        try:
            loc = page.locator(sel)
            n = loc.count()
            if not n:
                continue
            btn = loc.last
            # ★ 不先 scroll_into_view_if_needed（它可能 15s 超时直接失败），
            #   直接 click；短超时失败后依次 JS / force 降级
            #   （残留遮罩会拦原生点击，长超时只会白等，详见 CLICK_FAST_TIMEOUT）
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

    # ② JS 降级：按类名找 success 型按钮直接 click()
    if not clicked:
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


# ---------------------------------------------------------------- 组合流程

def ai_continue(page: Page,
                plot: str = "",
                model: str = "细腻版",
                associate: str = "正常",
                relate_count: int = 10,
                shortcut: str = "",
                shortcut_index: int = 0,
                shortcut_search: bool = False,
                start: bool = True,
                wait_dialog: float = 3.0,
                auto_accept: bool = False,
                min_words: int = 2100,
                max_words: int = 2300,
                max_retry: int = 5,
                gen_timeout: float = 240.0,
                hard_min: int = 0,
                best_effort: bool = True) -> bool:
    """完整流程：开弹窗 → 选快捷选项 → 选模型 → 填剧情 → 关联章节 → 开始续写
                →（可选）按字数自动「采纳 / 重新生成」。

    Args:
        plot:         后续剧情文本（前缀+内容+后缀 已由调用方拼好）
        model:        模型分类，默认「细腻版」
        associate:    联想能力，「正常」/「关闭」
        relate_count: 关联最近几章，默认 10
        shortcut:     ★ 快捷选项（提示词）关键词，如「强盛集团云霄」。
                      为空则不动这一项，保持站点默认。
        shortcut_index: 关键词命中多个时选第几个
        shortcut_search: 选之前先在面板搜索框里搜一下
        start:        是否点「开始 AI 续写」
        auto_accept:  ★ 是否开启「按字数自动决策」：
                        生成字数 ∈ [min_words, max_words] → 采纳使用
                        否则 → 重新生成（最多 max_retry 次）
        min_words:    字数下限（含）
        max_words:    字数上限（含）
        max_retry:    最多重新生成几次
        gen_timeout:  每次生成最多等多久（秒）
        hard_min:     ★ 硬下限（保底）：重试用完若当轮 ≥ hard_min 仍然采纳。
                      0 = 关闭。适合「提示词天生偏短」的场景，防止空转。
        best_effort:  ★ 重试耗尽仍未入区间时，是否采纳最后一轮（尽力而为）
    """
    global LAST_DECISION          # ★ 必须在函数体最前面声明
    print("=" * 58)
    print("  AI 续写正文")
    print(f"    模型     = {model}")
    print(f"    联想能力 = {associate}")
    print(f"    关联章节 = 最近 {relate_count} 章")
    if shortcut:
        print(f"    快捷选项 = {shortcut}")
    print(f"    剧情长度 = {len(plot)} 字")
    if auto_accept:
        print(f"    自动采纳 = 是（{min_words}~{max_words} 字，最多重生成 {max_retry} 次）")
    print("=" * 58)

    if not open_continue_dialog(page, wait=wait_dialog):
        return False

    # ⓪ ★ 选快捷选项（提示词）—— 必须在填剧情之前，
    #    因为换提示词可能会重置「续写要求」框里的内容
    if shortcut and shortcut != "跳过":
        before = current_shortcut(page)
        if shortcut in (before or ""):
            print(f"[ai] 快捷选项已是「{shortcut}」，跳过")
        else:
            pick_shortcut(page, keyword=shortcut, index=shortcut_index,
                          search_first=shortcut_search)

    # ① 选模型 + 联想能力（顺序：分类 → 模型卡片 → 联想能力 → 使用此模型）
    select_model(page, model=model, associate=associate)

    # ② 填后续剧情
    if plot.strip():
        fill_plot(page, plot)
    else:
        print("[ai] 未提供剧情文本，跳过填写")

    # ③ 关联最近 N 章
    # ★★ 必须检查返回值（2026-10-04）：旧代码忽略它，所以"关联章节没设上"
    #    这件事在日志里只是一行 ✗，流程照跑 —— 模型看不到前文，
    #    生成质量下降却没有任何告警。这是内容质量事故，必须显式警告。
    if relate_count and relate_count > 0:
        if not relate_chapters(page, count=relate_count):
            print(f"[ai] ⚠⚠ 警告：关联章节**未设置成功**（目标 最近{relate_count}章）！"
                  f"本次生成可能看不到前文，内容连贯性会变差。")
    else:
        print("[ai] relate_count<=0，跳过关联章节")

    _shot(page, "ai_ready")

    if not start:
        print("[ai] start=False，停在弹窗前（调试模式）")
        return True

    # ④ 开始
    ok = start_generate(page)
    if not ok:
        return False
    print("[ai] ✓ 已触发 AI 续写，等待生成 …")

    # ⑤ ★ 按字数自动决策
    if auto_accept:
        r = generate_with_word_check(page, min_words=min_words,
                                     max_words=max_words,
                                     max_retry=max_retry,
                                     gen_timeout=gen_timeout,
                                     hard_min=hard_min,
                                     best_effort=best_effort)
        print(f"[ai] 字数决策结果：{r['reason']}"
              f"（各轮字数 {r['tries']}）")
        LAST_DECISION = r          # ★ 供 UI 显示细节（已在上方 global）
        return r["ok"]

    LAST_DECISION = None
    return True


def ai_review(page: Page,
              text: str = "",
              model: str = "智慧版",
              model_card_name: str = "智慧版-6A",
              model_card_hint: str = "更懂作者意图，能稳定抓住风格",
              associate: str = "正常",
              requirement: str = "",
              req_tab: str = "快捷选项",
              instruction: str = "",
              open_chapter: str = "",
              chapter_index: int = 0,
              start: bool = True,
              wait_pane: float = 0.6,
              wait_done: bool = False,
              done_timeout: float = 600.0,
              replace: bool = False,
              select_all: bool = True) -> bool:
    """完整流程：开章节 → 开审稿面板 → 选模型 → 填待审文本 → 选审稿要求
                → 点生成 →（可选）等完成 →（可选）全选 →（可选）替换落盘。

    ★ 用户指定配置（2026-10-03）：
        模型     = 智慧版 → **智慧版-6A**
        联想能力 = **正常（0.7）**
        审稿要求 = 快捷选项里那句「强盛集团云霄拯救过稿计划（智慧5.6内测专属，审稿前10章）」
      ★ 审稿流程完整链路（用户明确要求）：
        ① 打开章节（否则正文为空）
        ② 点「生成」→ 等生成完（几分钟很正常）
        ③ ★ **全选正文** → ② 点「替换 / 插入」
           （不全选就变成「插入」，原文还在 → 前后拼接）

    Args:
        text:            待审文本；**给了就完全覆盖**（优先级最高）
        model:           模型分类，默认「智慧版」
        model_card_name: ★ 具体模型卡片名（分类与卡片名不同！），默认「智慧版-6A」
        model_card_hint: 用来精确定位是哪张模型卡（默认 6A 的描述）
        associate:       联想能力，「正常」= 0.7
        requirement:     审稿要求关键词（文字定位）
        req_tab:         「快捷选项」/「自定义」/「更多」
        instruction:     ★ 指令模板/追加要求，会跟当前章正文**拼在一起**
                         填进「待审文本」（类似续写的指令模板用法）
        open_chapter:    ★ 先打开哪一章（标题关键词，如「第2章」）；
                         留空则按 chapter_index 选第一个
        chapter_index:   open_chapter 为空时选第几个章节项
        start:           是否点「生成」
        wait_pane:       点开后等多久
        wait_done:       ★ 是否等审稿生成完成（等「替换 / 插入」出现）
        done_timeout:    ★ 等生成的最长时间（默认 600s；审稿慢，给足）
        replace:         ★ 是否在完成后点「替换 / 插入」落盘到正文
                         （需要 wait_done=True 才有意义）
        select_all:      ★ 点「替换」之前是否**全选正文**（默认 True）。
                         不选中的话「替换 / 插入」会变成**插入**，
                         原文保留 → 结果跟原稿前后拼接。

    Returns:
        bool 是否走完全流程；replace=True 时返回「替换」是否点到
    """
    print("=" * 58)
    print("  AI 审稿")
    print(f"    模型     = {model} → {model_card_name}")
    print(f"    联想能力 = {associate}")
    print(f"    审稿要求 = {requirement or '(不改)'}（{req_tab}）")
    if instruction:
        print(f"    追加指令 = {len(instruction)} 字（与正文拼接）")
    print(f"    待审文本 = {'（显式覆盖）' if text else ('（沿用页面自带）' if not instruction else '（正文+指令）')}")
    if wait_done:
        print(f"    等生成   = 是（最多 {done_timeout:.0f}s）")
    if replace:
        print(f"    替换落盘 = 是（先全选：{'是' if select_all else '否'}）")
    print("=" * 58)

    # ⓪ ★ 先打开章节（否则正文区为空，待审文本也是空的）
    #    ★ 不能靠 editor_ready 判断——`.tiptap.ProseMirror` 一直存在（空壳），
    #      必须用 need_text=True 看正文是否真有内容。
    if not editor_ready(page, need_text=True):
        open_chapter(page, which=open_chapter, index=chapter_index)
    else:
        print(f"[ai] 正文已就绪（{len(get_body_text(page))} 字），跳过打开章节")

    # ① 打开审稿面板（右侧抽屉）
    if not open_review_pane(page, wait=wait_pane):
        return False

    # ② 选模型
    #    ★★ 关键（2026-10-03 实测）：模型选择弹窗是**根级
    #       `.n-modal.model-picker-modal`**，跟审稿抽屉**平级**、不在抽屉里！
    #       所以：
    #         container      = 审稿抽屉（去那儿点开模型下拉）
    #         read_container = ".n-modal"（模型弹窗本体 / 回读模型名）
    #       （之前把 container 传成抽屉，导致
    #        `{抽屉} button:has-text('智慧版')` 找不到分类而失败。）
    select_model(page, model=model, associate=associate,
                 container=REVIEW_PANE_SEL,
                 read_container=".n-modal",
                 target=model_card_name,
                 card_hint=model_card_hint)

    # ③ 待审文本（显式覆盖 / 正文+指令拼接 / 沿用自带）
    fill_review_text(page, text, instruction=instruction)

    # ④ 审稿要求（先切 tab，再选提示词）
    if requirement:
        pick_review_requirement(page, keyword=requirement, tab=req_tab)

    if not start:
        print("[ai] start=False，停在「生成」前（调试模式）")
        return True

    # ⑤ 点「生成」
    if not start_review(page):
        return False

    # ⑥ ★ 等审稿跑完（几分钟很正常，耐心等）
    if wait_done:
        if not wait_review_done(page, timeout=done_timeout):
            return False
    elif not replace:
        # 不等也不替换 → 到「已触发生成」就算成功（老行为）
        return True

    # ⑦ ★ 全选正文（★ 否则「替换 / 插入」会变成「插入」，原文保留）
    if replace and select_all:
        select_all_body(page)

    # ⑧ ★ 点「替换 / 插入」把结果落进正文
    if replace:
        return replace_review_result(page)

    return True


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


def wait_body_change(page: Page, before_len: int = -1,
                     timeout: float = 20.0, poll: float = 1.0) -> int:
    """★ 等正文真正写入编辑器（采纳之后）。

    ★ 为什么要等：点了「采纳使用」≠ 正文立刻就在编辑器里。
      Naive UI 弹窗关闭 + 编辑器重渲染有延迟，
      不等的话下一环节（审稿）可能读到**空正文或旧正文**。

    Args:
        before_len: 采纳前的正文字数（-1 = 不比较，只要非空就算好）
        timeout:    最多等多久

    Returns:
        int 最终正文字数（超时则返回当前值）
    """
    print(f"[ai] --- 等正文写入（采纳前 {before_len} 字）---")
    last = [-1]
    # ★ 效率改造：原实现是「先 sleep(poll=1.0) 再检查」→ 条件早就满足也要
    #   白等 1 秒，且粗轮询让最坏情况再多等 1 秒。
    #   现在改为**先检查后等待**、并把轮询降到 0.1s：
    #   正文已经写好时立刻返回（≈0 秒），没写好也是 0.1s 粒度跟进。
    def _cond():
        cur = len(get_body_text(page))
        if cur != last[0]:
            print(f"[ai]   正文当前 {cur} 字")
            last[0] = cur
        return cur if (cur > 0 and (before_len < 0 or cur != before_len)) else None

    res = wait_until(_cond, timeout=timeout, interval=0.1, desc="正文写入")
    if res.ok:
        print(f"[ai] ✓ 正文已更新：{before_len} → {res.value} 字")
        return int(res.value)
    print(f"[ai] ⚠ 等正文写入超时（当前 {last[0]} 字）")
    return last[0] if last[0] > 0 else 0


def ai_auto_chapter(page: Page,
                    # ---- 续写参数 ----
                    plot: str = "",
                    gen_model: str = "细腻版",
                    gen_associate: str = "正常",
                    relate_count: int = 10,
                    shortcut: str = "",
                    shortcut_index: int = 0,
                    shortcut_search: bool = False,
                    min_words: int = 100,       # ★ 宽区间，避免重试
                    max_words: int = 5000,
                    max_retry: int = 0,
                    hard_min: int = 0,
                    best_effort: bool = True,
                    gen_timeout: float = 300.0,
                    # ---- 衔接参数 ----
                    close_dialog: bool = True,
                    settle: float = 2.0,
                    # ---- ★ 前置准备（流程开始前）----
                    prepare: bool = False,
                    prepare_app=None,
                    # ---- 审稿参数 ----
                    do_review: bool = True,
                    review_model: str = "智慧版",
                    review_card: str = "智慧版-6A",
                    review_card_hint: str = "",
                    review_associate: str = "正常",
                    review_req: str = "",
                    req_tab: str = "快捷选项",
                    review_instruction: str = "",
                    review_wait: float = 0.6,
                    review_done_timeout: float = 600.0,
                    replace: bool = True,
                    select_all: bool = True,
                    # ---- ★ 指定章节（批量跑章用）----
                    chapter: str = "") -> dict:
    """★★ 串起来跑：「AI 续写 → 采纳 → 关弹窗 → 等正文 → AI 审稿 → 替换」。

    这是用户要的**从 0 走完整一条章**的流程：
      ① 打开续写弹窗 → 选快捷选项/模型/联想 → 填剧情 → 关联章节 → 开始生成
      ② 按字数自动决策（宽区间默认 100~5000，基本**不会重试**）
      ③ ★ 关掉续写弹窗（否则模态拦截后续点击）
      ④ ★ 等正文真正写进编辑器
      ⑤ 打开审稿抽屉 → 选模型/联想/审稿要求 →（可选）追加提示词
      ⑥ 生成 → 等完成 → 全选正文 → 替换落盘

    Args:
        plot:          后续剧情文本
        gen_model:     续写模型（细腻版）
        gen_associate: 续写联想能力
        relate_count:  关联最近几章
        shortcut:      续写「快捷选项」关键词
        min_words/max_words: ★ 采纳字数区间（默认 100~5000，故意放宽避免重试）
        max_retry:     ★ 默认 0（不重试，一次过）
        hard_min:      保底采纳下限（0=关）
        best_effort:   重试耗尽仍采纳最后一轮
        gen_timeout:   单轮生成最长等待
        close_dialog:  ★ 续写后是否关弹窗（默认 True，必须）
        settle:        关弹窗后额外静置秒数
        do_review:     ★ 是否继续审稿（False 则只做续写部分）
        review_model / review_card / review_card_hint / review_associate /
        review_req / req_tab / review_instruction: 审稿参数（同 ai_review）
        review_wait:   打开审稿面板后等待
        review_done_timeout: 等审稿完成的最长秒数
        replace / select_all: 是否替换落盘 / 替换前全选

    Returns:
        dict 各阶段结果：{"gen": {...}, "body": int, "review": bool}
    """
    print("=" * 58)
    print("  ★ AI 自动走一章：续写 → 采纳 → 审稿 → 替换")
    print("=" * 58)

    result = {"gen": None, "body": -1, "review": False,
              "ok": False, "reason": ""}

    # ================= 阶段零：流程准备（可选）=================
    #  ★ 用户需求（2026-10-03）：一条龙之前先做「打开网站 + 保存 cookie/缓存」。
    #    UI 里已经单独给了「① 打开网站并保存」按钮；这里提供程序化入口，
    #    方便 CLI / 任务直接传 prepare=True。
    if prepare:
        print("\n" + "-" * 58)
        print("  【阶段零】流程准备（打开网站 → 保存 cookie/缓存）")
        print("-" * 58)
        try:
            from . import login as _L
            app = prepare_app
            if app is None:
                # 没有 App 就跳过（prepare 需要 app.context 才能导 state）
                st = _L.is_ready()
                print(f"[auto] 未提供 App，仅做本地检查：{st['message']}")
            else:
                r0 = _L.prepare_session(app, save=True, auto=True,
                                        wait_seconds=0, interactive=True)
                if not r0["ok"]:
                    print(f"[auto] ✗ 准备未完成：{r0['message']}")
                    result["prepare"] = r0
                    result["reason"] = f"流程准备未完成：{r0['message']}"
                    return result
                result["prepare"] = r0
                print("[auto] ✓ 准备就绪")
        except Exception as e:
            print(f"[auto] ⚠ 准备阶段异常（忽略，继续）：{e}")

    # ---- 记录采纳前正文（用来判断正文真的变了） ----
    if not editor_ready(page, need_text=True):
        # ★★ 根因修复（2026-10-03）：
        #   之前 `else: open_chapter(page)`（无参）会打开「倒序列表第0个 = 最新章」，
        #   导致「第1章的内容被写进第4章」这种错位。
        #   现在：
        #     - 指定了 chapter → 打开它
        #     - 没指定 → 打开「第1章」（最小章号），绝不切到最新章
        if chapter:
            open_chapter(page, which=chapter)
        else:
            nos = chapter_numbers(page)
            first = min(nos) if nos else 1
            print(f"[auto] 未指定章节，打开第{first}章（最小章号，避免切到最新章）")
            open_chapter(page, which=f"第{first}章")
    body_before = len(get_body_text(page))
    print(f"[auto] 起始正文：{body_before} 字")

    # ================= 阶段一：续写 =================
    print("\n" + "-" * 58)
    print("  【阶段一】AI 续写正文")
    print("-" * 58)
    gen_ok = ai_continue(
        page,
        plot=plot, model=gen_model, associate=gen_associate,
        relate_count=relate_count, shortcut=shortcut,
        shortcut_index=shortcut_index, shortcut_search=shortcut_search,
        start=True, auto_accept=True,
        min_words=min_words, max_words=max_words,
        max_retry=max_retry, gen_timeout=gen_timeout,
        hard_min=hard_min, best_effort=best_effort)
    result["gen"] = dict(LAST_DECISION) if LAST_DECISION else {"ok": gen_ok}
    if not gen_ok:
        print("[auto] ✗ 续写阶段失败，终止")
        result["reason"] = (result["gen"] or {}).get("reason") or "续写阶段失败"
        return result

    # ================= 阶段二：衔接 =================
    print("\n" + "-" * 58)
    print("  【阶段二】衔接（关弹窗 → 等正文写入）")
    print("-" * 58)
    if close_dialog:
        close_continue_dialog(page)

    # ★ 效率改造（2026-10-04 实测）：原来是固定 `time.sleep(settle=2.0)`，
    #   每章白等 2 秒。而且紧随其后的 `wait_body_change()` 本来就在轮询
    #   「正文写入」，所以那 2 秒是**重复等待**。
    #   现在把 settle 改成**有上限的非阻塞等待**：正文一变就立刻继续，
    #   没变也最多等 settle 秒（上限与旧行为一致，所以只会更快、不会更差）。
    if settle and settle > 0:
        _sr = wait_until(
            lambda: get_body_text(page).strip() != "" and
            len(get_body_text(page)) != body_before,
            timeout=float(settle), interval=0.06, desc="等正文写入(settle)")
        if _sr.ok:
            print(f"[auto] ✓ 正文已写入（{_sr.elapsed:.2f}s，settle 提前结束）")
        else:
            print(f"[auto]   settle 用满 {settle:.1f}s，交给 wait_body_change 继续等")

    # 等正文真的变了（采纳生效）
    new_len = wait_body_change(page, before_len=body_before, timeout=25.0)
    result["body"] = new_len
    if new_len <= 0:
        print("[auto] ✗ 正文为空，无法审稿，终止")
        result["reason"] = "采纳后正文为空"
        return result
    if body_before >= 0 and new_len == body_before:
        print(f"[auto] ⚠ 正文长度没变（{new_len}），可能采纳没生效，仍继续审稿")

    if not do_review:
        print("[auto] do_review=False，停在衔接完成")
        result["review"] = True
        # ★ do_review=False 时「续写+采纳」就是全部工作，故 ok 由续写决定
        result["ok"] = bool((result["gen"] or {}).get("ok", True))
        result["reason"] = "仅续写（未审稿）"
        return result

    # ================= 阶段三：审稿 =================
    print("\n" + "-" * 58)
    print("  【阶段三】AI 审稿")
    print("-" * 58)
    rev_ok = ai_review(
        page,
        model=review_model, model_card_name=review_card,
        model_card_hint=review_card_hint
        or MODEL_CARD_HINT.get(review_card, ""),
        associate=review_associate,
        requirement=review_req, req_tab=req_tab,
        instruction=review_instruction,
        start=True, wait_pane=review_wait,
        wait_done=True, done_timeout=review_done_timeout,
        replace=replace, select_all=select_all)
    result["review"] = rev_ok
    # ★ 统一返回契约：ok / reason 与 review / gen / body 并存。
    #   原实现没有 ok / reason，导致 `ai_batch_chapters` 读 `r.get("reason")`
    #   恒为 None、失败原因丢失；GUI 也只能靠 r.get("ok") 拿到 None。
    result["ok"] = bool(rev_ok)
    result["reason"] = ("审稿+替换完成" if rev_ok
                        else "审稿阶段未成功（详见 gen.reason 与截图）")

    # ★ 终局收尾：把审稿抽屉关掉，免得盖住正文区（影响后续读正文/下一章操作）
    if rev_ok and replace:
        try:
            close_review_pane(page)
        except Exception:
            pass

    print("\n" + "=" * 58)
    print("  ★ 一章自动流程结束")
    print(f"    续写结果 : {result['gen'].get('reason') if result['gen'] else '失败'}")
    print(f"    正文     : {body_before} → {result['body']} 字")
    print(f"    审稿替换 : {'✓ 完成' if rev_ok else '✗ 失败'}")
    print("=" * 58)
    return result


# ================================================================ 批量跑章 ★

def chapter_numbers(page: Page) -> List[int]:
    """只读：列出左栏所有章节的章号（按 DOM 顺序，站点是倒序）。

    章号从标题「第N章」里抠出来。失败/不识别返回 -1。
    """
    nos: List[int] = []
    try:
        items = page.locator(".chapter-item")
        n = items.count()
        for i in range(n):
            try:
                t = _text_of(items.nth(i), timeout=400)
            except Exception:
                t = ""
            m = re.search(r"第\s*(\d+)\s*章", t)
            nos.append(int(m.group(1)) if m else -1)
    except Exception:
        pass
    return nos


def ensure_chapter(page: Page, no: int, wait: float = 2.0,
                   max_new: int = 120) -> bool:
    """确保左栏存在「第 no 章」，缺就点「新建章节」自动补。

    ★ 实测（2026-10-03）：
      - 「新建章节」按钮 = `button:has-text('新建章节')`（左栏顶部，80x30）
      - 点一下会**立即**创建「第(当前最大+1)章」，标题自动递增、无需输入
        （会出现一个标题输入框，但已预填好标题，可忽略，按 Esc 失焦即可）
      - 章节列表是倒序（新章在最上、active）

    所以「按顺序补建」= 连续点 (no - 当前最大) 次即可。
    注意：只支持「往上补」（no > 当前最大）。若 no 已存在直接 True；
    若 no < 当前最大但不存在（比如删过导致跳号），无法靠新建补，返回 False。

    Args:
        no:      目标章号
        wait:    每次点完「新建章节」后的等待（秒）
        max_new: 最多新建几章（安全阀，防死循环）
    """
    nos = chapter_numbers(page)
    if no in nos:
        return True
    cur_max = max(nos) if nos else 0
    if no < cur_max:
        print(f"[ai] ✗ 第{no}章不存在且小于当前最大章号{cur_max}"
              f"（跳号，无法自动新建，需手动建/恢复）")
        return False
    need = no - cur_max
    if need > max_new:
        print(f"[ai] ✗ 要新建 {need} 章，超过安全上限 {max_new}")
        return False

    print(f"[ai] 缺第{no}章，连续新建 {need} 章（第{cur_max+1}~{no}章）…")
    for _ in range(need):
        if no in chapter_numbers(page):
            return True
        # 点「新建章节」
        clicked = False
        for attempt in range(3):
            try:
                btn = page.locator("button:has-text('新建章节')").first
                if _safe_click(btn, label="新建章节"):
                    clicked = True
                break
            except Exception:
                # 可能被标题输入框挡住 → 先 Esc 失焦再试
                try:
                    page.keyboard.press("Escape")
                except Exception:
                    pass
                time.sleep(0.6)
        if not clicked:
            print("[ai] ✗ 点「新建章节」失败")
            return False
        time.sleep(wait)
        # 点完可能聚焦标题输入框，Esc 失焦（不破坏已建章节）
        try:
            page.keyboard.press("Escape")
        except Exception:
            pass

    ok = no in chapter_numbers(page)
    if ok:
        print(f"[ai] ✓ 已新建到第{no}章")
    else:
        print(f"[ai] ✗ 新建后仍没有第{no}章（现有 {chapter_numbers(page)}）")
        _shot(page, "ai_ensure_chapter_failed")
    return ok


def ai_batch_chapters(page: Page,
                      start: int = 1,
                      end: int = 10,
                      plot: str = "",
                      plot_for: Optional[Callable[[int], str]] = None,
                      # ---- 续写参数（透传 ai_auto_chapter）----
                      gen_model: str = "细腻版",
                      gen_associate: str = "正常",
                      relate_count: int = 10,
                      shortcut: str = "",
                      min_words: int = 100,
                      max_words: int = 5000,
                      max_retry: int = 0,
                      best_effort: bool = True,
                      gen_timeout: float = 300.0,
                      # ---- 审稿参数 ----
                      do_review: bool = True,
                      review_model: str = "智慧版",
                      review_card: str = "智慧版-6A",
                      review_card_hint: str = "",
                      review_associate: str = "正常",
                      review_req: str = "",
                      req_tab: str = "快捷选项",
                      review_instruction: str = "",
                      review_done_timeout: float = 600.0,
                      replace: bool = True,
                      select_all: bool = True,
                      # ---- 节奏控制 ----
                      chapter_delay: float = 3.0,
                      auto_new: bool = True,
                      stop_on_fail: bool = False,
                      # ---- ★ 进度回调 / 中止（2026-10-04 新增）----
                      on_progress: Optional[Callable[[dict], None]] = None,
                      should_stop: Optional[Callable[[], bool]] = None) -> dict:
    """★★ 批量跑章：第 start ~ end 章，逐章「一条龙」。

    每章流程：
      ① 确保左栏有「第N章」（缺则点「新建章节」自动补）
      ② 切到「第N章」
      ③ 生成该章 plot：plot_for(N)（指令模板自动渲染）或共用 plot
      ④ ai_auto_chapter（续写 → 采纳 → 审稿 → 替换）
      ⑤ 下一章

    Args:
        start / end:  章号范围（含两端）
        plot:         所有章共用的剧情文本（plot_for 为 None 时用）
        plot_for:     ★ 回调，给定章号返回该章 plot。
                      典型：lambda no: proj.render_template(current=no)
                      这样指令模板里的 #@ 会自动替换成当前章的细纲。
        ... 其余透传给 ai_auto_chapter（见其签名）
        chapter_delay: 每章之间额外静置（等站点稳定）
        stop_on_fail: 某章失败就停（默认 False：失败也继续跑下一章）
        on_progress:  ★ 逐章进度回调，每章**开始前**和**结束后**各调一次：
                      ``{"no": 3, "total": 8, "index": 1,
                         "phase": "start"|"done",
                         "ok": True, "words": 2210, "elapsed": 130.2,
                         "reason": "", "done_count": 1, "ok_count": 1}``
                      界面用它画进度条 / 算 ETA / 填结果表。
                      回调抛异常会被吞掉，不影响跑章。
        should_stop:  ★ 中止判据（无参、返回 bool）。默认用模块级的
                      `cancel_requested`（界面点「停止」会置位）。
                      返回 True 时在**章与章之间**停下，并把 `aborted=True`
                      放进返回值。章内的长等待由 `wait_generation` /
                      `wait_review_done` 的 `should_abort` 负责立刻退出。

    Returns:
        {"total": N, "ok": M, "failed": [...], "results": [{no, ok, ...}],
         "aborted": bool, "elapsed": 秒}
    """
    if end < start:
        print("[batch] ✗ 结束章号 < 起始章号")
        return {"total": 0, "ok": 0, "failed": [], "results": [],
                "aborted": False, "elapsed": 0.0}

    _should_stop = should_stop or cancel_requested
    _total = end - start + 1
    _t_all = time.time()

    def _emit(**kw) -> None:
        """安全地发一次进度（回调异常不影响跑章）。"""
        if on_progress is None:
            return
        try:
            on_progress(kw)
        except Exception as e:
            print(f"[batch] ⚠ 进度回调异常（忽略）：{e}")

    print("=" * 60)
    print(f"  ★★ 批量跑章：第 {start} ~ {end} 章（共 {_total} 章）")
    print(f"     模型={gen_model} 联想={gen_associate} 关联={relate_count}章")
    print(f"     采纳 {min_words}~{max_words} 字 · 不重试 · 审稿={'是' if do_review else '否'}")
    print(f"     plot 来源={'指令模板自动渲染(#@=当前章)' if plot_for else ('固定('+str(len(plot))+'字)')}")
    print("=" * 60)

    results: List[dict] = []
    failed: List[int] = []
    aborted = False

    for no in range(start, end + 1):
        # ★★ 中止检查（章与章之间）：用户点「停止」后不要让下一章再开跑
        if _should_stop():
            print(f"[batch] ⏹ 收到停止请求，在第{no}章之前停下")
            aborted = True
            break

        index = no - start + 1
        t_ch = time.time()
        print("\n" + "#" * 60)
        print(f"#  第 {no}/{end} 章 开始（{index}/{_total}）")
        print("#" * 60)
        _emit(no=no, total=_total, index=index, phase="start",
              done_count=len(results),
              ok_count=sum(1 for x in results if x["ok"]),
              elapsed=time.time() - _t_all)

        # ① 确保章节存在（★ 逐章边建边跑；auto_new=False 时不新建）
        if auto_new:
            if not ensure_chapter(page, no):
                print(f"[batch] ✗ 第{no}章无法就位，跳过")
                failed.append(no)
                results.append({"no": no, "ok": False, "reason": "章节缺失",
                                "seconds": time.time() - t_ch})
                _emit(no=no, total=_total, index=index, phase="done",
                      ok=False, words=0, elapsed=time.time() - t_ch,
                      reason="章节缺失", done_count=len(results),
                      ok_count=sum(1 for x in results if x["ok"]))
                if stop_on_fail:
                    break
                continue
        elif no not in chapter_numbers(page):
            print(f"[batch] ✗ 第{no}章不存在且未开启自动新建，跳过")
            failed.append(no)
            results.append({"no": no, "ok": False,
                            "reason": "章节缺失(未开自动新建)",
                            "seconds": time.time() - t_ch})
            _emit(no=no, total=_total, index=index, phase="done",
                  ok=False, words=0, elapsed=time.time() - t_ch,
                  reason="章节缺失(未开自动新建)", done_count=len(results),
                  ok_count=sum(1 for x in results if x["ok"]))
            if stop_on_fail:
                break
            continue

        # ② 切到该章
        print(f"[batch] 切到第{no}章 …")
        open_chapter(page, which=f"第{no}章", wait=2.5)
        time.sleep(chapter_delay)

        # ③ 生成 plot
        this_plot = plot_for(no) if plot_for else plot
        if not this_plot.strip():
            print(f"[batch] ⚠ 第{no}章 plot 为空（细纲没填/模板没渲染出来）"
                  f"—— 仍继续，看站点是否自带内容")

        # ④ 一条龙
        try:
            r = ai_auto_chapter(
                page,
                plot=this_plot, chapter=f"第{no}章",
                gen_model=gen_model, gen_associate=gen_associate,
                relate_count=relate_count, shortcut=shortcut,
                min_words=min_words, max_words=max_words,
                max_retry=max_retry, best_effort=best_effort,
                gen_timeout=gen_timeout,
                close_dialog=True, settle=2.0,
                do_review=do_review,
                review_model=review_model, review_card=review_card,
                review_card_hint=review_card_hint,
                review_associate=review_associate,
                review_req=review_req, req_tab=req_tab,
                review_instruction=review_instruction,
                review_done_timeout=review_done_timeout,
                replace=replace, select_all=select_all)
        except Exception as e:
            print(f"[batch] ✗ 第{no}章异常：{e}")
            r = {"ok": False, "reason": f"异常 {e}"}

        # ★ 统一走 ai_auto_chapter 的新契约：优先用 ok，回退到 review
        r = r if isinstance(r, dict) else {"ok": bool(r)}
        ok = bool(r.get("ok", r.get("review", False)))
        # ★ 失败原因现在真的能拿到了（原来 r.get("reason") 恒为 None）
        reason = r.get("reason") or ""
        if not reason and r.get("gen"):
            reason = (r["gen"] or {}).get("reason") or ""
        secs = time.time() - t_ch
        # ★★ 区分「真的失败」和「被用户停止」：
        #   章内的长等待（等生成/等审稿）收到停止请求时会立刻退出并返回失败，
        #   但这不是章本身的问题 —— 不能算进失败列表，否则界面会把
        #   "被中止的那一章"报成失败，误导「从失败章重跑」。
        r_aborted = (not ok) and _should_stop()
        if r_aborted:
            reason = "已中止"
        results.append({"no": no, "ok": ok,
                        "body": r.get("body"),
                        "seconds": secs,
                        "reason": reason,
                        **({"aborted": True} if r_aborted else {})})
        _emit(no=no, total=_total, index=index, phase="done",
              ok=ok, aborted=r_aborted, words=r.get("body") or 0,
              elapsed=secs, reason=reason, done_count=len(results),
              ok_count=sum(1 for x in results if x["ok"]),
              total_elapsed=time.time() - _t_all)
        if ok:
            print(f"[batch] ✓ 第{no}章完成（{secs:.0f}s）")
        elif r_aborted:
            print(f"[batch] ⏹ 第{no}章因用户停止而中断（{secs:.0f}s）")
            aborted = True
            break
        else:
            print(f"[batch] ✗ 第{no}章失败（{secs:.0f}s）"
                  + (f"（{reason}）" if reason else ""))
            failed.append(no)
            if stop_on_fail:
                break

    ok_cnt = sum(1 for x in results if x["ok"])
    elapsed_all = time.time() - _t_all
    print("\n" + "=" * 60)
    if aborted:
        print(f"  ⏹ 批量跑章已中止：已完成 {ok_cnt}/{len(results)} 章"
              f"（目标 {_total} 章）")
    else:
        print(f"  ★ 批量跑章结束：{ok_cnt}/{len(results)} 章成功"
              f"{'（失败章：' + ','.join(map(str, failed)) + '）' if failed else ''}")
    for x in results:
        if not x["ok"]:
            print(f"    第{x['no']}章：{x['reason'] or '未记录原因'}")
    print("=" * 60)
    if not aborted:
        _shot(page, "batch_final")
    return {"total": len(results), "ok": ok_cnt,
            "failed": failed, "results": results,
            "aborted": aborted, "elapsed": elapsed_all}

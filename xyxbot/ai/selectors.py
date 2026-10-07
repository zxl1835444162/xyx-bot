"""选择器与站点常量表（纯数据，不依赖任何东西）。

本文件由 `xyxbot/ai.py` 拆分而来（Phase C1）。拆分时按 AST 依赖做了拓扑排序，
所以每个模块只 import 排在自己前面的模块，不存在循环引用。
"""

from __future__ import annotations

__all__ = ["AI_SELECTORS", "ANCHOR_TEXT", "ASSOCIATE_MARKS", "ASSOCIATE_SLIDER_SEL", "MODEL_CARD_HINT", "NUISANCE_DIALOGS", "RELATE_DROPDOWN_SEL", "REVIEW_CARD_ALT", "REVIEW_CARD_SEL", "REVIEW_PANE_SEL", "REVIEW_PANE_SEL_DEFINED", "REVIEW_RESULT_TEXT", "REVIEW_SEP", "_CONTINUE_MODAL_SEL"]


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


# ★★ 2026-10-06（用户问「他每次生成都选择了最近十章吗？为什么这次没选上」）：
#   老实现是**全页**扫 `.n-modal button.overflow-hidden`。
#   全页扫有个隐患：一旦上一章的续写弹窗还**残留在 DOM 里**
#   （我们已知本站会留残留弹窗/遮罩），而残留那个停在「最近10章」，
#   这里就可能读到**残留弹窗的值** ⇒ 误判"已是最近10章" ⇒ **静默跳过**，
#   而当前这个弹窗其实还是站点默认的「最近5章」。
#   ⇒ 现在改成：**优先只在"当前续写弹窗"里找**
#     （= 含「开始 AI 续写」按钮、且可见的那个 modal），
#     找不到再退回全页（保证不比旧行为差）。
_CONTINUE_MODAL_SEL = ".n-modal:has(button:has-text('开始 AI 续写'))"



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



REVIEW_SEP = "————————以下为待审正文————————"



# ---------------------------------------------------------------- 审稿结果落盘

# ★ 审稿生成完成后的「替换 / 插入」按钮。实测（2026-10-03 截图）：
#   抽屉底部按钮栏（两排）：
#     上排：继续追问 | ← 上一步
#     下排：🔄重新生成 | 复制 | 对比
#     最下：导出至作品 | 🟢替换 / 插入
#   → 「替换 / 插入」是**绿色（success 型）**，文字含空格和斜杠。
REVIEW_RESULT_TEXT = "替换"

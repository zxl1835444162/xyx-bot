"""模型、联想档位、剧情填写。

本文件由 `xyxbot/ai.py` 拆分而来（Phase C1）。拆分时按 AST 依赖做了拓扑排序，
所以每个模块只 import 排在自己前面的模块，不存在循环引用。
"""

from __future__ import annotations

from xyxbot.waiting import wait_gone, wait_until, wait_visible
from playwright.sync_api import Page
import time

from xyxbot.ai.current import _text_of, current_associate_level, current_model
from xyxbot.ai.elements import _cat_selected, _click_first, _fill_first, _safe_click, _shot
from xyxbot.ai.selectors import AI_SELECTORS, ASSOCIATE_MARKS, ASSOCIATE_SLIDER_SEL, MODEL_CARD_HINT

__all__ = ["fill_plot", "select_model", "set_associate_level"]



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

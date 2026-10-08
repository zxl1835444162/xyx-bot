"""新建作品（入口卡 → 弹窗 → 标题/类型 → 提交）。

本文件由原巨型模块拆分而来（Phase C2/C1），拆分时按 AST 依赖做了拓扑排序，
每个模块只 import 排在自己前面的模块，不存在循环引用。
"""

from __future__ import annotations

from xyxbot import actions as A
from xyxbot import config as C
from playwright.sync_api import Page
import random
import time

from xyxbot.books.editor import _shot, current_editor_title, is_in_editor
from xyxbot.books.list import count_existing_books, find_create_card, list_book_titles
from xyxbot.books.modal import close_activity_modal
from xyxbot.books.nav import goto_books

__all__ = ["click_create_book", "create_book", "fill_book_title", "open_create_dialog", "select_book_type", "submit_create"]


def click_create_book(page: Page, wait: float = 2.0) -> bool:
    """点击「新建作品」入口卡。

    安全策略：
        1. 先打印现场（有几张已有作品卡、都叫什么）
        2. 只用 `.create-card` 精确定位（绝不使用文本匹配）
        3. 用 click_strict 兜底，命中多个就拒绝点击
    """
    print("[books] --- 新建作品 ---")

    # 先清掉活动弹窗（会遮挡入口卡，导致点击降级或失败）
    close_activity_modal(page, verbose=False)

    existing = count_existing_books(page)
    titles = list_book_titles(page)
    print(f"[books] 当前已有作品 {existing} 个: {titles}")
    print("[books] ⚠ 注意：已有作品里可能就有叫「新建作品」的，"
          "因此不使用文字匹配，改用 .create-card 精确定位")

    card = find_create_card(page)
    if card is None:
        print("[books] ✗ 找不到「新建作品」入口卡（.create-card）")
        p = C.SHOTS / f"fail-create-card-{int(time.time())}.png"
        page.screenshot(path=str(p), full_page=True)
        print(f"[books] 已截图 {p}")
        return False

    # 校验：确认拿到的是入口卡，而不是已有作品卡
    try:
        cls = card.get_attribute("class") or ""
        if "create-card" not in cls:
            print(f"[books] ✗ 定位到的元素 class 不含 create-card: {cls}")
            return False
        print(f"[books] ✓ 定位到入口卡，class={cls}")
    except Exception as e:
        print(f"[books] 校验 class 失败: {e}")

    # 点击（click_strict 再兜一层）
    ok = A.click_strict(
        page,
        C.BOOK_SELECTORS["create_card"],
        label="新建作品入口卡",
        expect_unique=True,
    )
    if not ok:
        return False

    time.sleep(wait)
    print(f"[books] 点击后 URL: {page.url}")
    return True



def open_create_dialog(page: Page, timeout: float = 8.0) -> bool:
    """等待「新建作品」弹窗出现。

    实测弹窗特征：标题「创建作品后可使用AI功能」，含「作品名称」「作品类型」。
    """
    print("[books] 等待新建作品弹窗 ...")
    deadline = time.time() + timeout
    while time.time() < deadline:
        for sel in C.BOOK_SELECTORS["create_dialog"]:
            try:
                if page.locator(sel).first.is_visible(timeout=800):
                    print(f"[books] ✓ 弹窗出现: {sel}")
                    return True
            except Exception:
                continue
        time.sleep(0.5)
    print("[books] ⚠ 未检测到新建作品弹窗（可能直接进入编辑器）")
    return False



def fill_book_title(page: Page, title: str) -> bool:
    """在弹窗里填作品名称。

    实测：输入框默认值就是「新建作品」，上限 30 字。
    """
    if not title:
        return True
    for sel in C.BOOK_SELECTORS["dialog_title_input"]:
        try:
            loc = page.locator(sel).first
            if not loc.is_visible(timeout=1200):
                continue
            loc.click()
            loc.fill("")               # 清掉默认的「新建作品」
            A.human_pause(0.1, 0.25)
            for ch in title:
                loc.type(ch, delay=random.randint(50, 130))
            val = loc.input_value()
            print(f"[books] ✓ 作品名称已填: {val!r}  (选择器={sel})")
            return val.strip() == title.strip()
        except Exception as e:
            print(f"[books] 填标题失败 ({sel}): {str(e)[:60]}")
            continue
    print("[books] ⚠ 没找到作品名称输入框")
    return False



def select_book_type(page: Page, kind: str = "novel") -> bool:
    """选择作品类型。kind: 'novel'(小说) / 'script'(剧本)。

    实测默认已选中「小说」，所以只在需要剧本时才真的点。
    """
    if kind not in ("novel", "script"):
        return False

    key = "dialog_type_novel" if kind == "novel" else "dialog_type_script"
    label = "小说" if kind == "novel" else "剧本"

    for sel in C.BOOK_SELECTORS[key]:
        try:
            loc = page.locator(sel).first
            if loc.is_visible(timeout=1200):
                loc.click()
                print(f"[books] ✓ 已选择作品类型: {label}")
                A.human_pause(0.2, 0.5)
                return True
        except Exception:
            continue
    print(f"[books] ⚠ 未能选择类型 {label}（可能默认已是）")
    return False



def submit_create(page: Page, wait: float = 4.0) -> bool:
    """点「提交」完成创建。"""
    ok = A.click(page, C.BOOK_SELECTORS["dialog_confirm_btn"],
                 label="提交（创建作品）", shot_on_fail=False)
    if ok:
        print("[books] 已提交，等待创建完成 ...")
        time.sleep(wait)
    return ok



# ---------------------------------------------------------------- 组合流程

def create_book(page: Page, title: str = "", book_type: str = "novel",
                intro: str = "", submit: bool = True) -> bool:
    """完整流程：进作品页 → 关广告弹窗 → 点「+ 新建作品」入口卡 → 填表单 → 提交。

    关键点：入口卡用 `.create-card` 精确定位，
    绝不能用 `text=新建作品` —— 站点上已有作品可能就叫「新建作品1」「新建作品」，
    纯文本匹配会命中多个（实测命中 4 个），必然误点。

    Args:
        title:     作品名；留空则用站点默认（弹窗内已有默认值「新建作品」）
        book_type: "novel" 小说 / "script" 剧本
        intro:     作品简介（选填，站点上限 500 字）
        submit:    是否点击「提交」创建；False 则只填完表单停下（调试用）

    Returns:
        bool: 是否成功走完创建流程
    """
    print("=" * 58)
    print("  新建作品流程开始")
    print(f"    标题   = {title or '（站点默认）'}")
    print(f"    类型   = {'小说' if book_type == 'novel' else '剧本'}")
    print(f"    简介   = {intro or '（留空）'}")
    print(f"    提交   = {submit}")
    print("=" * 58)

    # ① 进作品页
    if not goto_books(page):
        print("[books] ✗ 无法进入作品页，终止")
        return False

    # ② 记录创建前的基线（用于事后校验）
    before = count_existing_books(page)
    before_titles = list_book_titles(page)
    print(f"[books] 创建前：{before} 部作品 {before_titles}")

    # ③ 关掉可能挡住入口卡的运营/活动弹窗
    close_activity_modal(page)

    # ④ 点入口卡（严格模式，只用 .create-card）
    if not click_create_book(page):
        print("[books] ✗ 点击「新建作品」入口卡失败，终止")
        return False

    # ⑤ 等创建弹窗出现
    if not open_create_dialog(page, timeout=8.0):
        print("[books] ✗ 创建弹窗未出现（可能直接进了编辑器，或弹窗结构变了）")
        print(f"[books] 当前 URL: {page.url}")
        _shot(page, "create_dialog_missing")
        return False

    # ⑥ 填标题：留空就用站点默认，不动它
    if title:
        if fill_book_title(page, title):
            print(f"[books] ✓ 标题已填: {title}")
        else:
            print("[books] ⚠ 没找到标题输入框，将使用站点默认名")
    else:
        print("[books] 未指定标题，保留弹窗默认值")

    # ⑦ 选类型
    select_book_type(page, book_type)

    # ⑧ 填简介（选填）
    if intro:
        if A.fill(page, C.BOOK_SELECTORS["dialog_intro_input"],
                  intro, label="作品简介"):
            print("[books] ✓ 简介已填")
        else:
            print("[books] ⚠ 简介输入框未找到，跳过")

    # ⑨ 提交
    if not submit:
        print("[books] submit=False，表单已填好，停在弹窗前（调试模式）")
        _shot(page, "create_dialog_filled")
        return True

    if not submit_create(page, wait=4.0):
        print("[books] ✗ 提交失败")
        _shot(page, "create_submit_fail")
        return False

    # ⑩ 校验：实测提交后会直接跳进新作品的编辑器，所以要先判断跳转
    time.sleep(2.5)
    print(f"[books] 当前 URL: {page.url}")

    # ★ 实测结论（2026-10-03）：提交成功后 SPA 会跳到编辑器，
    #   原来的作品卡列表从 DOM 上消失，此时 list_book_titles 必然返回 []，
    #   绝不能因此判定「创建失败」。
    if is_in_editor(page):
        title = current_editor_title(page)
        print(f"[books] ✓ 已进入编辑器，当前作品: {title or '（读不到标题）'}")
        print("[books] ✓ 新建成功（编辑器直达，不回到作品页）")
        return True

    # 没跳编辑器 → 应该还在作品页，比对作品数
    after = count_existing_books(page)
    after_titles = list_book_titles(page)
    print(f"[books] 作品数: {before} → {after}")
    print(f"[books] 作品列表: {after_titles}")

    new_ones = [t for t in after_titles if t not in before_titles]
    if new_ones:
        print(f"[books] ✓ 新增作品: {new_ones}")
        return True

    # 兜底：可能跳到了别的路由，回去看一眼
    B_goto = goto_books(page, wait=3.0)
    if B_goto:
        after_titles = list_book_titles(page)
        new_ones = [t for t in after_titles if t not in before_titles]
        if new_ones:
            print(f"[books] ✓ 新增作品（返回作品页后确认）: {new_ones}")
            return True

    print("[books] ⚠ 未检测到新增作品，请查看截图确认")
    _shot(page, "create_verify_unknown")
    return False

# -*- coding: utf-8 -*-
"""验证 ai_auto_chapter 带 shortcut 时，续写阶段能否选中「快捷选项」提示词"""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))  # 仓库根
from src.app import App
from src import books as B
from src import ai as AI

with App(headless=False) as app:
    page = app.page
    B.open_book(page, "新建作品1", console_pick=False, wait=3.0)
    AI.dismiss_dialogs(page)
    AI.open_chapter(page, which="第2章")

    # ★ 只验证续写前半段：开弹窗 → 选提示词 → 看是否选中
    AI.open_continue_dialog(page, wait=3.0)
    AI.select_model(page, model="细腻版", associate="正常")

    print("\n>>> 当前快捷选项：", repr(AI.current_shortcut(page)))
    print(">>> 调用 pick_shortcut('强盛集团云霄') …")
    r = AI.pick_shortcut(page, keyword="强盛集团云霄最强续写")
    print(f">>> pick_shortcut = {r}")
    print(">>> 选完后快捷选项：", repr(AI.current_shortcut(page)))
    app.shot("_verify_shortcut")

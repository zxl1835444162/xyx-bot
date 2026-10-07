# -*- coding: utf-8 -*-
"""★★ 从 0 走一遍完整一章：续写 → 采纳 → 关弹窗 → 等正文 → 审稿 → 替换

用户要求：
  - 字数限制宽一点，避免重试
  - 看看能否**直接走完**（中途不人工干预）
  - 验证「生成完 → 审稿」的衔接（这是用户最担心的）
"""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))  # 仓库根
from src.app import App
from src import books as B
from src import ai as AI

INSTRUCTION = ("请按爽文节奏审改以下正文，重点检查毒点与逻辑断裂。\n"
               "不要新增剧情，不要改变原有情节走向。")

with App(headless=False) as app:
    page = app.page
    if not B.open_book(page, "新建作品1", console_pick=False, wait=3.0):
        print("✗ 打开作品失败"); sys.exit(1)

    AI.dismiss_dialogs(page)
    AI.open_chapter(page, which="第2章")
    before = AI.get_body_text(page)
    print(f"\n[E2E] 起始正文 = {len(before)} 字")

    t0 = time.time()
    r = AI.ai_auto_chapter(
        page,
        # ★ 续写：宽区间 + 一次过
        plot="继续推进剧情，让主角拿到关键证据。",
        gen_model="细腻版", gen_associate="正常", relate_count=10,
        # ★★ 本轮修复点：续写必须选「强盛集团云霄最强续写」那条提示词
        #    （用户指出上一轮 E2E 漏选了强盛）
        shortcut="强盛集团云霄最强续写",
        min_words=100, max_words=5000, max_retry=0,
        best_effort=True, gen_timeout=300.0,
        # ★ 衔接
        close_dialog=True, settle=2.0,
        # ★ 审稿
        do_review=True,
        review_model="智慧版", review_card="智慧版-6A",
        review_associate="正常",
        review_req="强盛集团云霄拯救过稿计划",
        review_instruction=INSTRUCTION,
        review_done_timeout=600.0,
        replace=True, select_all=True)

    # ★★ 结论段测量（2026-10-03 修正）
    #    旧版这里直接 get_body_text()，结果读到的可能是别处（面板/切章），
    #    导致「最终正文 216 字」「原稿残留 True」这两个**假异常**。
    #    现在：替换完成后，先把审稿抽屉关掉、重开本章，再读正文。
    time.sleep(1.5)
    AI.close_review_pane(page)          # 关右侧审稿抽屉（若有）
    AI.dismiss_dialogs(page)
    AI.open_chapter(page, which="第2章", wait=2.5)   # ★ 重开第2章再读
    time.sleep(1.0)
    after = AI.get_body_text(page)
    el = time.time() - t0
    print("\n" + "=" * 62)
    print("  ★★ 一条龙 E2E 结论")
    print("=" * 62)
    gen = r.get("gen") or {}
    print(f"  总耗时       : {el:.0f}s ({el/60:.1f} 分钟)")
    print(f"  ① 续写/采纳  : {gen.get('reason', '?')}")
    print(f"  ② 采纳后正文 : {r.get('body')} 字")
    print(f"  ③ 审稿+替换  : {'✓ 完成' if r.get('review') else '✗ 失败'}")
    print(f"  最终正文     : {len(before)} → {len(after)} 字")
    # ★ 注意：替换会把「审稿结果」覆盖原稿，所以原稿开头**本来就不该**在最终正文里
    print(f"  原稿残留     : {before[:30] in after}  （应为 False）")
    # ★ 判「续写弹窗」+「审稿抽屉」都关了（旧版只判续写弹窗，终局会误报 False）
    print(f"  弹窗已关     : 续写={not AI.continue_dialog_open(page)} "
          f"审稿抽屉={not AI.review_pane_open(page)}")
    app.shot("_e2e_final")

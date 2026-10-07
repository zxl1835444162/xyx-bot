# -*- coding: utf-8 -*-
"""定点探针 3：把 open_review_pane 的**每一句**都计时，定位那 8.5 秒。

已排除的可能：
  · 不是 wait_until 在等（diag_review2 里它只轮询了 2 次、0.08s 就成功了）
  · 不是 dismiss_dialogs（诊断里它 11 次共 0.52s）
本探针把函数体抄一遍、逐句计时，直接看时间花在哪一行。

★ 零 AI 额度消耗。
"""

from __future__ import annotations

import os
import sys
import time

# 仓库根：本文件位于 tools/<组>/ 下，退三层
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

# ★ 输出被重定向到文件/管道时 Windows 会用 GBK，日志里的 ⚠/✓ 会让
#   print 直接抛 UnicodeEncodeError（实测）。先加固编码。
try:
    from xyxbot.console import enable_utf8

    enable_utf8()
except Exception:
    pass

OUT = os.path.join(ROOT, "artifacts", "diag", "review-probe3.txt")
os.makedirs(os.path.dirname(OUT), exist_ok=True)
_f = open(OUT, "w", encoding="utf-8", buffering=1)


def say(*a):
    line = " ".join(str(x) for x in a)
    _f.write(line + "\n")
    print(line)


def step(label, fn):
    t0 = time.perf_counter()
    try:
        r = fn()
        err = ""
    except Exception as e:
        r = None
        err = f" !! {type(e).__name__}: {str(e).splitlines()[0][:50]}"
    el = time.perf_counter() - t0
    say(f"      {label:<44s} {el*1000:>9.1f}ms  "
        f"{('→ ' + str(r)[:26]) if r is not None else ''}{err}")
    return el, r


def main() -> int:
    from xyxbot import ai as AI
    from xyxbot import books as B
    from xyxbot.app import App

    say("=" * 80)
    say(f"  open_review_pane 逐句计时   {time.strftime('%H:%M:%S')}")
    say("=" * 80)
    say(f"  btn_review 选择器 = {AI.AI_SELECTORS['btn_review']}")
    say(f"  REVIEW_PANE_SEL   = {AI.REVIEW_PANE_SEL!r}")

    app = App(headless=False)
    app.start()
    page = app.page
    try:
        B.open_book(page, "新建作品1", index=0, wait=3.0, console_pick=False)
        AI.dismiss_dialogs(page)
        AI.open_chapter(page, which="第1章")

        for label, prelude in (("A 干净场景", None),
                               ("B 完整前置后", True)):
            say(f"\n--- {label} ---")
            if prelude:
                AI.open_continue_dialog(page, wait=3.0)
                AI.select_model(page, model="细腻版", associate="正常")
                AI.fill_plot(page, "探针占位剧情，不会提交。")
                AI.relate_chapters(page, 10)
                AI._shot(page, "probe3_ready")
                AI.close_continue_dialog(page)

            say(f"    （起始 review_pane_open = {AI.review_pane_open(page)}）")
            t_all = time.perf_counter()

            step("① dismiss_dialogs(verbose=True)",
                 lambda: AI.dismiss_dialogs(page, verbose=True))
            step("   顶层 review_pane_open(page)",
                 lambda: AI.review_pane_open(page))

            def _click():
                btn = page.locator(AI.AI_SELECTORS["btn_review"][0]).first
                c = btn.count()
                if not c:
                    return "no-btn"
                try:
                    btn.scroll_into_view_if_needed(
                        timeout=AI.CLICK_FAST_TIMEOUT)
                except Exception:
                    pass
                try:
                    btn.click(timeout=AI.CLICK_FAST_TIMEOUT)
                    return "native"
                except Exception:
                    btn.evaluate("e => e.click()")
                    return "js"

            step("② 点「AI审稿」（原生→JS）", _click)
            step("   点击后 review_pane_open(page)",
                 lambda: AI.review_pane_open(page))
            step("③ wait_until(审稿面板出现, 7.6s)",
                 lambda: AI.wait_until(AI.review_pane_open, timeout=7.6,
                                       interval=0.08,
                                       desc="审稿面板出现"))
            step("   最终 review_pane_open(page)",
                 lambda: AI.review_pane_open(page))
            say(f"    合计 {time.perf_counter()-t_all:.2f}s")

            AI.close_review_pane(page)
    finally:
        try:
            app.stop()
        except Exception:
            pass
        _f.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

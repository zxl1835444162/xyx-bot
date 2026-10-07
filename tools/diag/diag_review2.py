# -*- coding: utf-8 -*-
"""定点探针 2：把 `review_pane_open` 的**每一次轮询**都记下来。

背景：diag_latency 里 `open_review_pane` 要 8.53s，日志显示
    ✓ 已点「AI审稿」（第 1 次，JS 降级）
      面板未出现，重试…
    ✓ 审稿面板已在
即：轮询了 7.6 秒都说"没出现"，紧接着重试的第一句判断却说"已在"。
但在干净场景下单独点「AI审稿」，面板是**立刻**就出现的（0.2s）。

本探针复现 diag_latency 的完整前置动作（选模型 + 填剧情 + 关联章节），
然后把 `review_pane_open` 换成一个逐次记录的版本，看它到底看到了什么。

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

OUT = os.path.join(ROOT, "artifacts", "diag", "review-probe2.txt")
os.makedirs(os.path.dirname(OUT), exist_ok=True)
_f = open(OUT, "w", encoding="utf-8", buffering=1)


def say(*a):
    line = " ".join(str(x) for x in a)
    _f.write(line + "\n")
    print(line)


PROBE_JS = r"""
() => {
  const vis = e => !!(e.offsetWidth || e.offsetHeight || e.getClientRects().length);
  const cs = [...document.querySelectorAll('.n-card-content')];
  const withAnchor = cs.filter(c => c.innerText.includes('待审文本'));
  const modals = [...document.querySelectorAll('.n-modal')]
      .map(m => ({cls: (m.className||'').toString().slice(0,50), vis: vis(m)}));
  return {
    cc_n: cs.length,
    cc_first_vis: cs.length ? vis(cs[0]) : null,
    withAnchor_n: withAnchor.length,
    withAnchor_vis_n: withAnchor.filter(vis).length,
    modals: modals,
    mask: document.querySelectorAll('.n-modal-mask').length,
    body_anchor: document.body.innerText.includes('待审文本'),
  };
}
"""


def main() -> int:
    from xyxbot import ai as AI
    from xyxbot import books as B
    from xyxbot.app import App

    say("=" * 80)
    say(f"  审稿面板判据逐次记录   {time.strftime('%H:%M:%S')}")
    say("=" * 80)

    app = App(headless=False)
    app.start()
    page = app.page
    try:
        B.open_book(page, "新建作品1", index=0, wait=3.0, console_pick=False)
        AI.dismiss_dialogs(page)
        AI.open_chapter(page, which="第1章")

        # 备份原判据，然后换成"记账版"
        orig = AI.review_pane_open
        log: list = []

        def spy(pg) -> bool:
            r = orig(pg)
            try:
                d = pg.evaluate(PROBE_JS)
            except Exception as e:
                d = {"err": str(e)[:40]}
            log.append((time.perf_counter(), r, d))
            return r

        AI.review_pane_open = spy

        say("\n【A】干净场景：直接 open_review_pane")
        log.clear()
        t0 = time.perf_counter()
        ok = AI.open_review_pane(page)
        say(f"  → {ok}  耗时 {time.perf_counter()-t0:.2f}s  轮询 {len(log)} 次")
        for i, (_, r, d) in enumerate(log[:6]):
            say(f"     #{i} pane={r} {d}")
        AI.review_pane_open = orig
        AI.close_review_pane(page)

        say("\n【B】完整前置（选模型+填剧情+关联章节）后 open_review_pane")
        AI.open_continue_dialog(page, wait=3.0)
        AI.select_model(page, model="细腻版", associate="正常")
        AI.fill_plot(page, "探针占位剧情，不会提交。")
        AI.relate_chapters(page, 10)
        AI._shot(page, "probe_ready")
        AI.close_continue_dialog(page)

        AI.review_pane_open = spy
        log.clear()
        t0 = time.perf_counter()
        ok = AI.open_review_pane(page)
        el = time.perf_counter() - t0
        say(f"  → {ok}  耗时 {el:.2f}s  轮询 {len(log)} 次")
        for i, (_, r, d) in enumerate(log):
            if i < 8 or i % 15 == 0 or i == len(log) - 1:
                say(f"     #{i:3d} t={time.perf_counter()-t0:5.2f}s "
                    f"pane={r} {d}")
        AI.review_pane_open = orig

        say("\n【C】前置之后，DOM 里还残留什么（此时抽屉应已打开）")
        AI.review_pane_open = orig
        d = page.evaluate(PROBE_JS)
        say(f"  {d}")
        try:
            AI.close_review_pane(page)
        except Exception:
            pass
    finally:
        try:
            app.stop()
        except Exception:
            pass
        _f.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

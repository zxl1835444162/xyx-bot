# -*- coding: utf-8 -*-
"""定点探针：审稿抽屉到底什么时候才算"出现"？

背景（diag_latency 实测）：
    开审稿抽屉 = 8.5s/章，是剩下最大的单笔开销
    wait_until(review_pane_open, timeout=7.6s) → **63 次轮询全部 False**
    紧接着的重试里 `review_pane_open()` 又一次就 True

这不合常理（1ms 之内从 False 变 True），所以要么
    ① 判据 `REVIEW_PANE_SEL=".n-card-content:has-text('待审文本')"`
       匹配到的是**隐藏的那个**，真正的抽屉早就出来了；
    ② 要么抽屉真的要 ~7.6 秒才渲染出「待审文本」这几个字。
本探针就是来区分这两种情况的。

★ 零 AI 额度消耗：只点「AI审稿」开面板，不点生成。
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
    from src.console import enable_utf8

    enable_utf8()
except Exception:
    pass

OUT = os.path.join(ROOT, "artifacts", "diag", "review-probe.txt")
os.makedirs(os.path.dirname(OUT), exist_ok=True)
_f = open(OUT, "w", encoding="utf-8", buffering=1)


def say(*a):
    line = " ".join(str(x) for x in a)
    _f.write(line + "\n")
    print(line)


SAMPLE_JS = r"""
() => {
  const vis = e => !!(e.offsetWidth || e.offsetHeight || e.getClientRects().length);
  const out = {};
  const cs = document.querySelectorAll('.n-card-content');
  out.card_content_n = cs.length;
  out.card_content_with_anchor = 0;
  out.card_content_visible_with_anchor = 0;
  out.first_card_content_visible = cs.length ? vis(cs[0]) : null;
  cs.forEach(c => {
    if (c.innerText.includes('待审文本')) {
      out.card_content_with_anchor++;
      if (vis(c)) out.card_content_visible_with_anchor++;
    }
  });
  // 各种"抽屉/右侧工作区"候选标记
  const marks = {
    right_workspace: '.chapter-right-workspace',
    n_drawer: '.n-drawer',
    n_drawer_body: '.n-drawer-body',
    side_pane_card: '.n-card.chapter-side-pane-card',
    side_pane_c: '.n-card.chapter-side-pane-c',
    card_header_close: '.n-card-header button[aria-label=close]',
    radio_button: '.n-radio-button',
    base_selection: '.n-base-selection',
  };
  out.marks = {};
  for (const [k, sel] of Object.entries(marks)) {
    const els = document.querySelectorAll(sel);
    out.marks[k] = [els.length, [...els].filter(vis).length];
  }
  out.url = location.hash;
  out.body_has_anchor = document.body.innerText.includes('待审文本');
  return out;
}
"""


def main() -> int:
    from src import ai as AI
    from src import books as B
    from src.app import App

    say("=" * 78)
    say(f"  审稿抽屉出现时机探针   {time.strftime('%H:%M:%S')}")
    say("=" * 78)

    app = App(headless=False)
    app.start()
    page = app.page
    try:
        B.open_book(page, "新建作品1", index=0, wait=3.0, console_pick=False)
        AI.dismiss_dialogs(page)
        AI.open_chapter(page, which="第1章")

        # 确认起点：抽屉应该是关着的
        say(f"\n  起点 review_pane_open = {AI.review_pane_open(page)}")
        say(f"  起点 DOM 采样：{page.evaluate(SAMPLE_JS)}")
        say(f"  REVIEW_PANE_SEL = {AI.REVIEW_PANE_SEL!r}")
        say(f"  REVIEW_CARD_SEL = {AI.REVIEW_CARD_SEL!r}")
        say(f"  ANCHOR_TEXT     = {AI.ANCHOR_TEXT!r}")

        for rnd in (1, 2, 3):
            say("\n" + "-" * 78)
            if rnd >= 2:
                # ★★ 关键：复现 diag_latency 里的"前置状态" ——
                #    先开一次续写弹窗再关掉，然后才点 AI审稿（实测那里要 8.5s）
                say(f"  第 {rnd} 轮：★ 先「开续写弹窗 → 关闭」再点「AI审稿」")
                t = time.perf_counter()
                AI.open_continue_dialog(page, wait=3.0)
                say(f"    open_continue_dialog  {time.perf_counter()-t:.2f}s")
                t = time.perf_counter()
                AI.close_continue_dialog(page)
                say(f"    close_continue_dialog {time.perf_counter()-t:.2f}s")
                d0 = page.evaluate(SAMPLE_JS)
                say(f"    关闭后 DOM：cc={d0['card_content_n']} "
                    f"pane={AI.review_pane_open(page)}  "
                    f"mask_count={page.locator('.n-modal-mask').count()}")
            else:
                say(f"  第 {rnd} 轮：干净状态直接点「AI审稿」")
            say("-" * 78)

            btn = page.locator(AI.AI_SELECTORS["btn_review"][0]).first
            say(f"  AI审稿按钮 count={btn.count()} visible="
                f"{btn.is_visible() if btn.count() else None}")
            t0 = time.perf_counter()
            AI._safe_click(btn, label="AI审稿(探针)")
            say(f"  已点击（{time.perf_counter()-t0:.2f}s）")

            t0 = time.perf_counter()
            for i in range(100):          # 100 × 0.2s = 20s
                el = time.perf_counter() - t0
                d = page.evaluate(SAMPLE_JS)
                pane = AI.review_pane_open(page)
                m = d["marks"]
                say(f"  t={el:5.2f}s pane={str(pane):5s} "
                    f"body_anchor={str(d['body_has_anchor']):5s} "
                    f"cc={d['card_content_n']:2d}"
                    f"(anchor {d['card_content_with_anchor']}/"
                    f"vis {d['card_content_visible_with_anchor']}) "
                    f"| drawer={m['n_drawer']} "
                    f"side_card={m['side_pane_card']} "
                    f"right_ws={m['right_workspace']} "
                    f"radio={m['radio_button']} "
                    f"sel={m['base_selection'][0]}")
                if pane and d["body_has_anchor"]:
                    say(f"  ★ 在 t={el:.2f}s 首次判定「面板已出现」")
                    break
                time.sleep(max(0.0, 0.2 - (time.perf_counter() - t0 - el)))

            # 收尾：关掉抽屉
            t0 = time.perf_counter()
            ok = AI.close_review_pane(page)
            say(f"  close_review_pane = {ok}  （{time.perf_counter()-t0:.2f}s）")
            time.sleep(1.0)
    finally:
        try:
            app.stop()
        except Exception:
            pass
        _f.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

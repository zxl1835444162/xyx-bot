# -*- coding: utf-8 -*-
"""定点探针：只测几个「疑似 15 秒黑洞」的点，跑两遍（SLOW_MO=80 / 0）对比。

★ 零 AI 额度消耗：只开弹窗、只点「最近3章」这类无副作用按钮。
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

# SLOW_MO 必须在 import config 之前设好
_argv = sys.argv[1:]
SLOW = _argv[0] if _argv else "80"
os.environ["XYX_SLOW_MO"] = SLOW

OUT = os.path.join(ROOT, "artifacts", "diag", f"probe-slow{SLOW}.txt")
os.makedirs(os.path.dirname(OUT), exist_ok=True)
_f = open(OUT, "w", encoding="utf-8", buffering=1)


def say(*a):
    line = " ".join(str(x) for x in a)
    _f.write(line + "\n")
    print(line)


def timed(label, fn, repeat=1):
    vals = []
    err = ""
    res = None
    for _ in range(repeat):
        t0 = time.perf_counter()
        try:
            res = fn()
            err = ""
        except Exception as e:
            err = f"{type(e).__name__}: {str(e).splitlines()[0][:60]}"
            res = None
        vals.append(time.perf_counter() - t0)
    avg = sum(vals) / len(vals)
    say(f"  {label:<46s} {avg*1000:>9.1f}ms  "
        f"min={min(vals)*1000:6.1f} max={max(vals)*1000:7.1f}  "
        f"→ {str(res)[:40]!r} {err}")
    return avg


def main() -> int:
    say("=" * 78)
    say(f"  定点探针  SLOW_MO={SLOW}ms   {time.strftime('%H:%M:%S')}")
    say("=" * 78)

    from src import ai as AI
    from src import books as B
    from src.app import App

    from src import config as C
    say(f"  config.SLOW_MO = {C.SLOW_MO}  DEFAULT_TIMEOUT = {C.DEFAULT_TIMEOUT}")

    app = App(headless=False)
    app.start()
    page = app.page
    try:
        if not B.open_book(page, "新建作品1", index=0, wait=3.0,
                           console_pick=False):
            say("✗ 打不开作品")
            return 1
        AI.dismiss_dialogs(page)
        AI.open_chapter(page, which="第1章")

        say("\n--- ① 慢速期（开弹窗前，DOM 里没有这些元素）---")
        timed("locator('[class*=association-level]').count()",
              lambda: page.locator("[class*=association-level]").count(), 3)
        timed("locator('.n-modal').count()",
              lambda: page.locator(".n-modal").count(), 3)

        say("\n--- ② 打开续写弹窗 ---")
        timed("AI.open_continue_dialog(page, wait=3.0)",
              lambda: AI.open_continue_dialog(page, wait=3.0))

        say("\n--- ③ 弹窗开着时，关联章节 / 联想 元素是否真的存在 ---")
        timed("locator('[class*=association-level]').count()",
              lambda: page.locator("[class*=association-level]").count(), 3)
        timed("  .first.inner_text()  ★默认 15s 超时",
              lambda: page.locator("[class*=association-level]")
                        .first.inner_text(), 2)
        timed("  .first.inner_text(timeout=250)",
              lambda: page.locator("[class*=association-level]")
                        .first.inner_text(timeout=250), 2)
        timed("  .first.is_visible()",
              lambda: page.locator("[class*=association-level]")
                        .first.is_visible(), 2)

        say("\n--- ④ AI.current_associate_level() 本体 ---")
        timed("AI.current_associate_level(page)", 
              lambda: AI.current_associate_level(page), 2)

        say("\n--- ⑤ 「不存在元素」上，各种默认超时的真实代价 ---")
        timed("locator('.__nope__').first.inner_text()  默认超时",
              lambda: page.locator(".__nope__").first.inner_text(), 2)
        timed("locator('.__nope__').first.inner_text(timeout=150)",
              lambda: page.locator(".__nope__").first.inner_text(timeout=150), 2)
        timed("locator('.__nope__').first.click(timeout=150)",
              lambda: page.locator(".__nope__").first.click(timeout=150), 2)

        say("\n--- ⑥ 单次点击的真实成本（点「最近3章」，无副作用）---")
        three = page.locator(".n-modal button").filter(
            has_text="最近3章").first
        say(f"    最近3章 存在? count={three.count()} vis={three.is_visible()}")
        timed("button.click()  默认超时",
              lambda: page.locator(".n-modal button")
                        .filter(has_text="最近3章").first.click(), 4)
        timed("button.click(timeout=1200)",
              lambda: page.locator(".n-modal button")
                        .filter(has_text="最近3章").first
                        .click(timeout=1200), 2)
        timed("button.evaluate('e=>e.click()')  JS 点击",
              lambda: page.locator(".n-modal button")
                        .filter(has_text="最近3章").first
                        .evaluate("e => e.click()"), 3)
        timed("scroll_into_view_if_needed()",
              lambda: page.locator(".n-modal button")
                        .filter(has_text="最近3章").first
                        .scroll_into_view_if_needed(), 3)

        say("\n--- ⑦ 项目里的辅助函数 ---")
        timed("AI._visible(page, AI_SELECTORS['btn_continue'])",
              lambda: AI._visible(page, AI.AI_SELECTORS["btn_continue"]), 3)
        timed("AI.chapter_numbers(page)",
              lambda: AI.chapter_numbers(page), 2)
        timed("AI.get_body_text(page)",
              lambda: AI.get_body_text(page), 2)
        timed("AI.dismiss_dialogs(page, verbose=False)",
              lambda: AI.dismiss_dialogs(page, verbose=False), 2)
        timed("AI.editor_ready(page, need_text=True)",
              lambda: AI.editor_ready(page, need_text=True), 2)

        say("\n--- ⑧ 关联章节按钮：真实结构与当前值 ---")
        info = page.evaluate("""() => {
          const out = [];
          document.querySelectorAll('.n-modal button').forEach(b => {
            const t = (b.innerText || '').replace(/\\s+/g, ' ').trim();
            if (/^(清空|选择章节|最近\\d+章)$/.test(t)) {
              const cs = getComputedStyle(b);
              out.push({t: t, cls: (b.className||'').toString(),
                        vis: !!(b.offsetWidth||b.offsetHeight),
                        cls2: cs.overflow, pad: cs.paddingLeft + '/' + cs.paddingRight,
                        svg: b.querySelectorAll('svg').length,
                        rect: b.getBoundingClientRect()});
            }
          });
          return out;
        }""")
        for it in info:
            say(f"    {it['t']:<8s} vis={it['vis']} svg={it['svg']} "
                f"overflow={it['cls2']} pad={it['pad']} "
                f"x={it['rect']['x']:.0f} w={it['rect']['width']:.0f}")
            say(f"        cls={it['cls']}")

        AI.close_continue_dialog(page)
    finally:
        try:
            app.stop()
        except Exception:
            pass
        _f.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

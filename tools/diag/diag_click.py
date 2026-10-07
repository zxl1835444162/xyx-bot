# -*- coding: utf-8 -*-
"""拆解 _click_first：为什么单次点击要 ~3 秒？

实测背景（diag_latency 第二次运行）：
    ai._click_first   4 次   9.08s   → 约 2.27s/次
    其中 open_continue_dialog 的 3 次 ≈ 3.0s/次
而裸测量：
    locator.click()           122ms (SLOW_MO=80)
    scroll_into_view_if_needed 123ms
    => 理论上 250ms 就够，多出来的 2.7 秒必须定位到具体哪一步。

★ 零 AI 额度消耗：只点「AI续写正文」开/关弹窗，不点生成。
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

OUT = os.path.join(ROOT, "artifacts", "diag", "click-breakdown.txt")
os.makedirs(os.path.dirname(OUT), exist_ok=True)
_f = open(OUT, "w", encoding="utf-8", buffering=1)


def say(*a):
    line = " ".join(str(x) for x in a)
    _f.write(line + "\n")
    print(line)


def t(label, fn):
    t0 = time.perf_counter()
    r = None
    err = ""
    try:
        r = fn()
    except Exception as e:
        err = f"{type(e).__name__}: {str(e).splitlines()[0][:70]}"
    el = time.perf_counter() - t0
    say(f"    {label:<44s} {el*1000:>8.1f}ms  {('→ ' + str(r)[:28]) if r is not None else ''}{err}")
    return el


def main() -> int:
    from xyxbot import ai as AI
    from xyxbot import books as B
    from xyxbot.app import App

    say("=" * 78)
    say(f"  _click_first 拆解   {time.strftime('%H:%M:%S')}")
    say("=" * 78)

    app = App(headless=False)
    app.start()
    page = app.page
    try:
        B.open_book(page, "新建作品1", index=0, wait=3.0, console_pick=False)
        AI.dismiss_dialogs(page)
        AI.open_chapter(page, which="第1章")

        sels = AI.AI_SELECTORS["btn_continue"]
        say(f"\n  btn_continue 选择器共 {len(sels)} 条：")
        for s in sels:
            say(f"    - {s}")

        for rnd in (1, 2, 3):
            say(f"\n--- 第 {rnd} 轮（弹窗先关掉，模拟真实场景）---")
            AI.close_continue_dialog(page)
            AI.dismiss_dialogs(page, verbose=False)
            say(f"    弹窗是否开着: {AI.continue_dialog_open(page)}")

            # ① 复刻 _click_first 的每一步
            loc = None
            t("_visible(page, btn_continue) 整段",
              lambda: AI._visible(page, sels))
            loc, sel = AI._visible(page, sels)
            if loc is None:
                say("    ✗ 找不到按钮，跳过")
                continue
            say(f"    命中选择器: {sel}")

            t("loc.scroll_into_view_if_needed()",
              lambda: loc.scroll_into_view_if_needed())
            t("loc.click(timeout=4000)  ★原生点击",
              lambda: loc.click(timeout=4000))
            say(f"    → 点击后弹窗: {AI.continue_dialog_open(page)}")

            # ② 关掉再试：短超时 + 各种变体
            AI.close_continue_dialog(page)
            AI.dismiss_dialogs(page, verbose=False)
            loc2, _ = AI._visible(page, sels)
            if loc2 is not None:
                t("loc.click(timeout=800)",
                  lambda: loc2.click(timeout=800))
                AI.close_continue_dialog(page)
                AI.dismiss_dialogs(page, verbose=False)
                loc3, _ = AI._visible(page, sels)
                t("loc.click(force=True, timeout=800)",
                  lambda: loc3.click(force=True, timeout=800))
                AI.close_continue_dialog(page)
                AI.dismiss_dialogs(page, verbose=False)
                loc4, _ = AI._visible(page, sels)
                t("loc.evaluate('e=>e.click()')  JS",
                  lambda: loc4.evaluate("e => e.click()"))
                AI.close_continue_dialog(page)

            # ③ 整段 _click_first 的真实耗时
            AI.dismiss_dialogs(page, verbose=False)
            t("AI._click_first(...) 整段",
              lambda: AI._click_first(page, sels, label="probe"))
            AI.close_continue_dialog(page)

        # ④ 干扰弹窗 / 遮罩是否在拦截
        say("\n--- 遮罩与拦截排查 ---")
        t("locator('.n-modal-mask').count()",
          lambda: page.locator(".n-modal-mask").count())
        t("locator('.n-modal-container').count()",
          lambda: page.locator(".n-modal-container").count())
        info = page.evaluate("""() => {
          const out = {masks: [], btns: []};
          document.querySelectorAll('.n-modal-mask, .n-modal-container,'+
                                    '.n-modal-body-wrapper').forEach(e => {
            const cs = getComputedStyle(e);
            out.masks.push({cls: (e.className||'').toString().slice(0,60),
                            pe: cs.pointerEvents, vis: cs.visibility,
                            op: cs.opacity, z: cs.zIndex,
                            w: e.offsetWidth, h: e.offsetHeight});
          });
          document.querySelectorAll('button').forEach(b => {
            const t = (b.innerText||'').replace(/\\s+/g,' ').trim();
            if (t.includes('AI续写正文')) {
              const r = b.getBoundingClientRect();
              const cs = getComputedStyle(b);
              out.btns.push({t: t.slice(0,20), vis: cs.visibility,
                             pe: cs.pointerEvents, dis: b.disabled,
                             x: Math.round(r.x), y: Math.round(r.y),
                             w: Math.round(r.width), h: Math.round(r.height),
                             topEl: (document.elementFromPoint(
                                 r.x + r.width/2, r.y + r.height/2) || {})
                                 .className?.toString().slice(0,50) || ''});
            }
          });
          return out;
        }""")
        say("  遮罩/容器：")
        for m in info["masks"]:
            say(f"    {m}")
        say("  「AI续写正文」按钮：")
        for b in info["btns"]:
            say(f"    {b}")
    finally:
        try:
            app.stop()
        except Exception:
            pass
        _f.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

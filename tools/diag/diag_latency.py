# -*- coding: utf-8 -*-
"""实时延迟诊断（不消耗任何 AI 额度、不修改任何正文）。

目标：把「自动化操作本身」的耗时精确归因，回答三个问题——
  ① 每章到底白等了多少秒？等在哪一行？
  ② 一次浏览器往返（count / is_visible / click）究竟多少毫秒，
     轮询 40ms 是"很轻"还是"很贵"？
  ③ 关联章节区（relate_chapters）第 2 章之后为什么找不到按钮组？
     ── 现场抓真实 DOM，不再靠猜。

★ 安全边界：只做「开弹窗 / 展开下拉 / 读 DOM / 关弹窗」。
  绝不点「开始 AI 续写」或「生成」，因此不会产生任何 AI 费用，
  也不会改动作品正文。

用法：
    .venv312\\Scripts\\python.exe diag_latency.py
    set XYX_DIAG_BOOK=新建作品1 & set XYX_DIAG_CHAPTER=第2章
"""

from __future__ import annotations

import functools
import json
import os
import sys
import time
from datetime import datetime

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

REAL_SLEEP = time.sleep
REAL_PERF = time.perf_counter

DIAG_DIR = os.path.join(ROOT, "artifacts", "diag")
os.makedirs(DIAG_DIR, exist_ok=True)
REPORT = os.path.join(DIAG_DIR, "latency-report.txt")
_out = open(REPORT, "w", encoding="utf-8", buffering=1)


def say(*a) -> None:
    line = " ".join(str(x) for x in a)
    _out.write(line + "\n")
    try:
        print(line)
    except Exception:
        pass


# ============================================================ 仪表 ①：sleep 归因

SLEEPS: list[tuple[str, str, float]] = []   # (当前函数, 调用点, 秒数)
STACK: list[str] = []


def cur_fn() -> str:
    return STACK[-1] if STACK else "(顶层)"


class TimeShim:
    """顶替模块里的 `time`，把每一次 sleep 记到「谁调的、哪一行」。"""

    def __init__(self, real):
        self._r = real

    def __getattr__(self, k):
        return getattr(self._r, k)

    def sleep(self, sec):
        fr = sys._getframe(1)
        site = f"{os.path.basename(fr.f_code.co_filename)}:{fr.f_lineno}"
        REAL_SLEEP(sec)
        SLEEPS.append((cur_fn(), site, float(sec)))


# ============================================================ 仪表 ②：函数计时

FUNCS: dict[str, dict] = {}
TREE: list[list] = []          # [name, 子函数累计耗时]


def wrap_fn(mod, name: str) -> None:
    orig = getattr(mod, name)
    key = f"{mod.__name__.split('.')[-1]}.{name}"

    @functools.wraps(orig)
    def inner(*a, **k):
        m = FUNCS.setdefault(key, {"n": 0, "wall": 0.0, "child": 0.0,
                                   "sleep": 0.0, "false": 0})
        t0 = REAL_PERF()
        n_sleep_before = len(SLEEPS)
        STACK.append(key)
        TREE.append([key, 0.0])
        try:
            r = orig(*a, **k)
            if r is False:
                m["false"] += 1
            return r
        finally:
            STACK.pop()
            el = REAL_PERF() - t0
            child = TREE.pop()[1]
            if TREE:
                TREE[-1][1] += el
            m["n"] += 1
            m["wall"] += el
            m["child"] += child
            m["sleep"] += sum(s[2] for s in SLEEPS[n_sleep_before:])

    setattr(mod, name, inner)


# ============================================================ 仪表 ③：条件等待

WAITS: list[dict] = []


def wrap_wait(mod, name: str) -> None:
    orig = getattr(mod, name)

    @functools.wraps(orig)
    def inner(*a, **k):
        t0 = REAL_PERF()
        r = orig(*a, **k)
        el = REAL_PERF() - t0
        WAITS.append({
            "where": cur_fn(),
            "kind": name,
            "elapsed": el,
            "polls": getattr(r, "polls", None),
            "ok": getattr(r, "ok", None),
            "desc": (k.get("desc") or getattr(r, "detail", "") or ""),
        })
        return r

    setattr(mod, name, inner)


# ============================================================ 仪表 ④：原始往返

RAW: list[tuple[str, float, bool]] = []


def raw(label: str, fn):
    t0 = REAL_PERF()
    ok = True
    try:
        v = fn()
    except Exception:
        ok = False
        v = None
    RAW.append((label, REAL_PERF() - t0, ok))
    return v


# ============================================================ 报告工具

def hr(ch: str = "=", n: int = 74) -> None:
    say(ch * n)


def table_fn(title: str, *, min_wall: float = 0.0) -> None:
    rows = [(k, v) for k, v in FUNCS.items() if v["wall"] >= min_wall]
    rows.sort(key=lambda kv: -kv[1]["wall"])
    hr()
    say(f"  {title}")
    hr()
    say(f"  {'函数':<34s}{'次数':>5s}{'总耗时':>10s}{'自身':>10s}{'sleep':>9s}")
    hr("-")
    tot_wall = tot_self = tot_sleep = 0.0
    for k, v in rows:
        self_t = v["wall"] - v["child"]
        tot_wall += v["wall"]
        tot_self += self_t
        tot_sleep += v["sleep"]
        say(f"  {k:<34s}{v['n']:>5d}{v['wall']:>9.2f}s"
            f"{self_t:>9.2f}s{v['sleep']:>8.2f}s")
    hr("-")
    say(f"  {'合计':<34s}{'':>5s}{tot_wall:>9.2f}s{tot_self:>9.2f}s"
        f"{tot_sleep:>8.2f}s")
    say("  ★「自身」= 总耗时 − 子函数耗时，即这段代码自己花的净时间")
    hr()


def table_sleep(title: str) -> None:
    agg: dict[tuple[str, str], list] = {}
    for fn_name, site, sec in SLEEPS:
        e = agg.setdefault((fn_name, site), [0, 0.0])
        e[0] += 1
        e[1] += sec
    rows = sorted(agg.items(), key=lambda kv: -kv[1][1])
    hr()
    say(f"  {title}（共 {len(SLEEPS)} 次，合计 {sum(s[2] for s in SLEEPS):.2f}s）")
    hr()
    if not rows:
        say("  （无任何 sleep —— 全部已条件化）")
    else:
        say(f"  {'函数':<30s}{'调用点':<16s}{'次数':>5s}{'合计':>9s}")
        hr("-")
        for (fn_name, site), (n, sec) in rows:
            say(f"  {fn_name:<30s}{site:<16s}{n:>5d}{sec:>8.2f}s")
    hr()


def table_waits(title: str) -> None:
    hr()
    say(f"  {title}（共 {len(WAITS)} 次，合计 "
        f"{sum(w['elapsed'] for w in WAITS):.2f}s）")
    hr()
    if not WAITS:
        say("  （无）")
        hr()
        return
    say(f"  {'调用者':<28s}{'类型':<14s}{'耗时':>8s}{'轮询':>6s}{'结果':>6s}  desc")
    hr("-")
    for w in sorted(WAITS, key=lambda x: -x["elapsed"]):
        ok = "✓" if w["ok"] else "✗"
        say(f"  {w['where']:<28s}{w['kind']:<14s}{w['elapsed']:>7.3f}s"
            f"{str(w['polls']):>6s}{ok:>6s}  {w['desc'][:34]}")
    # 轮询成本统计
    tot_polls = sum(w["polls"] or 0 for w in WAITS)
    say("-")
    say(f"  轮询总次数 = {tot_polls}；平均每次等待 "
        f"{sum(w['elapsed'] for w in WAITS) / len(WAITS):.3f}s")
    hr()


def table_raw(title: str) -> None:
    hr()
    say(f"  {title}")
    hr()
    if not RAW:
        say("  （无）")
        hr()
        return
    vals = sorted(r[1] for r in RAW)
    n = len(vals)
    med = vals[n // 2]
    say(f"  样本 {n} 次   最小 {vals[0]*1000:.1f}ms   "
        f"中位 {med*1000:.1f}ms   平均 {sum(vals)/n*1000:.1f}ms   "
        f"最大 {vals[-1]*1000:.1f}ms")
    # 按标签聚合
    agg: dict[str, list] = {}
    for label, el, ok in RAW:
        agg.setdefault(label, []).append(el)
    hr("-")
    say(f"  {'操作':<34s}{'次数':>5s}{'平均':>10s}{'最大':>10s}")
    hr("-")
    for label, vs in sorted(agg.items(), key=lambda kv: -sum(kv[1])):
        say(f"  {label:<34s}{len(vs):>5d}"
            f"{sum(vs)/len(vs)*1000:>9.1f}ms{max(vs)*1000:>9.1f}ms")
    hr()


# ============================================================ DOM 抓取

DUMP_JS = r"""
() => {
  const R = {buttons: [], group: null, groupSel: null, popups: [], hint: ''};
  const modal = document.querySelector('.n-modal');
  if (!modal) { R.hint = 'no .n-modal'; return R; }

  const btns = Array.from(modal.querySelectorAll('button'));
  R.buttons = btns.map(b => ({
      t: (b.innerText || '').replace(/\s+/g, ' ').trim().slice(0, 40),
      vis: !!(b.offsetWidth || b.offsetHeight || b.getClientRects().length),
      cls: (b.className || '').toString().slice(0, 90),
      svg: b.querySelectorAll('svg').length
  }));

  // 用「清空」锚定按钮组那一行
  const clear = btns.find(b => (b.innerText || '').includes('清空'));
  if (clear) {
    let row = clear.parentElement;
    for (let i = 0; i < 4 && row; i++) {
      const bs = row.querySelectorAll('button');
      if (bs.length >= 3) break;
      row = row.parentElement;
    }
    if (row) {
      R.group = row.outerHTML.slice(0, 4000);
      const p = row.parentElement;
      let path = [];
      let cur = row;
      while (cur && cur !== document.body) {
        let s = cur.tagName.toLowerCase();
        if (cur.className && typeof cur.className === 'string') {
          s += '.' + cur.className.trim().split(/\s+/).slice(0, 3).join('.');
        }
        path.unshift(s);
        cur = cur.parentElement;
      }
      R.groupSel = path.join(' > ').slice(0, 400);
      R.groupRect = row.getBoundingClientRect();
    }
  } else {
    R.hint = 'modal 里没有「清空」按钮';
  }

  // 任何含「最近」的浮层/弹层
  const cands = document.querySelectorAll(
    '.n-popover, .n-base-select-menu, [class*=dropdown], [class*=popover], [class*=follower]');
  cands.forEach(el => {
    const t = (el.innerText || '').replace(/\s+/g, ' ').trim();
    if (t.includes('最近')) {
      const cs = getComputedStyle(el);
      R.popups.push({
        t: t.slice(0, 160),
        display: cs.display, visibility: cs.visibility, opacity: cs.opacity,
        rect: el.getBoundingClientRect(),
        cls: (el.className || '').toString().slice(0, 120)
      });
    }
  });

  // 「最近N章」相关元素全景（含隐藏的）
  R.recent = [];
  document.querySelectorAll('*').forEach(el => {
    if (el.children.length) return;
    const t = (el.innerText || '').trim();
    if (/^最近\d+章$/.test(t)) {
      const cs = getComputedStyle(el);
      const r = el.getBoundingClientRect();
      R.recent.push({
        t: t, tag: el.tagName.toLowerCase(),
        cls: (el.className || '').toString().slice(0, 80),
        vis: !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length),
        display: cs.display, visibility: cs.visibility,
        w: Math.round(r.width), h: Math.round(r.height),
        inModal: !!el.closest('.n-modal')
      });
    }
  });
  return R;
}
"""


def dump_dom(page, tag: str) -> dict:
    t0 = REAL_PERF()
    try:
        d = page.evaluate(DUMP_JS)
    except Exception as e:
        d = {"hint": f"evaluate 失败: {e}"}
    RAW.append((f"DOM 全量扫描 ({tag})", REAL_PERF() - t0, "hint" not in d))

    hr()
    say(f"  ◆ DOM 抓取 [{tag}]")
    hr()
    say(f"  hint: {d.get('hint', '')}")
    say(f"  按钮组选择器路径: {d.get('groupSel')}")
    say(f"  按钮组位置: {d.get('groupRect')}")

    say("\n  --- .n-modal 内所有 button ---")
    for i, b in enumerate(d.get("buttons", [])):
        say(f"    [{i:2d}] vis={str(b['vis']):5s} svg={b['svg']} "
            f"t={b['t']!r}")
        say(f"          cls={b['cls']}")

    say("\n  --- 「最近N章」元素全景（含隐藏） ---")
    for r in d.get("recent", []):
        say(f"    {r['t']:<8s} tag={r['tag']:<8s} vis={str(r['vis']):5s} "
            f"display={r['display']:<12s} visibility={r['visibility']:<10s} "
            f"size={r['w']}x{r['h']} inModal={r['inModal']}")
        say(f"          cls={r['cls']}")

    say("\n  --- 含「最近」的浮层 ---")
    for p in d.get("popups", []):
        say(f"    display={p['display']:<10s} vis={p['visibility']:<10s} "
            f"op={p['opacity']:<5s} rect={p['rect']}")
        say(f"          t={p['t']!r}")
        say(f"          cls={p['cls']}")

    if d.get("group"):
        fn = os.path.join(DIAG_DIR, f"relate-group-{tag}.html")
        with open(fn, "w", encoding="utf-8") as f:
            f.write(d["group"])
        say(f"\n  → 按钮组 outerHTML 已存: {os.path.basename(fn)} "
            f"({len(d['group'])} 字符)")

    hr()
    return d


# ============================================================ 主流程

def main() -> int:
    book = os.getenv("XYX_DIAG_BOOK", "新建作品1")
    chapter = os.getenv("XYX_DIAG_CHAPTER", "")

    hr("#")
    say(f"#  实时延迟诊断  {datetime.now():%Y-%m-%d %H:%M:%S}")
    say(f"#  作品={book!r}  章节={chapter!r}")
    say(f"#  SLOW_MO={os.getenv('XYX_SLOW_MO', '(默认 80)')}ms  "
        f"headless={os.getenv('XYX_HEADLESS', '0')}")
    hr("#")

    # ---- 装仪表（必须在 import src.ai 之后、跑流程之前）
    from xyxbot import ai as AI
    from xyxbot import books as B
    from xyxbot import login as L
    from xyxbot import waiting as W

    shim = TimeShim(time)
    AI.time = shim
    B.time = shim
    L.time = shim

    for mod, names in (
        (AI, ["dismiss_dialogs", "_click_first", "_fill_first",
              "open_continue_dialog", "current_model",
              "current_associate_level", "set_associate_level",
              "select_model", "fill_plot", "current_shortcut",
              "open_shortcut_panel", "wait_shortcut_loaded",
              "close_shortcut_panel", "pick_shortcut", "relate_chapters",
              "wait_generation", "get_body_text", "open_chapter",
              "open_review_pane", "close_review_pane", "review_pane_open",
              "pick_review_requirement", "fill_review_text",
              "select_all_body", "wait_review_done", "replace_review_result",
              "wait_body_change", "close_continue_dialog",
              "continue_dialog_open", "dismiss_review_confirm",
              "ai_continue", "ai_review", "ai_auto_chapter"]),
        (B, ["goto_books", "_click_sidebar_books", "list_books",
             "open_book", "close_activity_modal", "is_in_editor"]),
        (L, ["open_site_page", "is_logged_in"]),
    ):
        for nm in names:
            if hasattr(mod, nm):
                try:
                    wrap_fn(mod, nm)
                except Exception as e:
                    say(f"  [warn] 无法包裹 {nm}: {e}")

    for nm in ("wait_until", "wait_gone", "wait_visible", "wait_hidden"):
        if hasattr(W, nm):
            wrap_wait(W, nm)
    # ai/books 是 `from .waiting import ...` 绑定的名字，需单独替换
    for mod in (AI, B):
        for nm in ("wait_until", "wait_gone", "wait_visible"):
            if hasattr(mod, nm):
                wrap_wait(mod, nm)

    # ---- 启动
    from xyxbot.app import App

    t_boot = REAL_PERF()
    app = None
    app = App(headless=False)
    app.start()
    t_boot = REAL_PERF() - t_boot
    page = app.page
    say(f"\n[boot] 浏览器启动 + 恢复登录态 = {t_boot:.2f}s")

    try:
        # ---------------------------------------------------- 阶段 1
        hr("#")
        say("#  阶段 1：打开作品 → 打开章节（量「进入」成本）")
        hr("#")
        ok = B.open_book(page, book, index=0, wait=3.0, console_pick=False)
        say(f"\n[1] open_book = {ok}")
        if not ok:
            say("✗ 无法打开作品，诊断中止")
            return 1

        AI.dismiss_dialogs(page)
        which = chapter
        if not which:
            nums = AI.chapter_numbers(page)
            which = f"第{nums[-1]}章" if nums else "第1章"
        say(f"[1] 将在左栏找: {which!r}")
        AI.open_chapter(page, which=which)

        # ---------------------------------------------------- 阶段 2
        hr("#")
        say("#  阶段 2：量「一次浏览器往返」的真实成本")
        hr("#")
        for label, fn in (
            ("locator(sel).count()  存在元素",
             lambda: page.locator(".n-modal").count()),
            ("locator(sel).count()  不存在元素",
             lambda: page.locator(".definitely-not-here-xyz").count()),
            ("locator(sel).first.is_visible()  不存在",
             lambda: page.locator(".definitely-not-here-xyz")
                       .first.is_visible(timeout=60)),
            ("is_visible()  存在但不可见(<head>)",
             lambda: page.locator("head").first.is_visible(timeout=60)),
            ("locator(sel).first.count()  存在",
             lambda: page.locator("body").first.count()),
            ("get_attribute('class')  body",
             lambda: page.locator("body").first.get_attribute("class")),
            ("inner_text()  正文区",
             lambda: page.locator("body").first.inner_text(timeout=1500)),
            ("evaluate('1+1')  纯 JS 往返",
             lambda: page.evaluate("() => 1 + 1")),
            ("page.url  读属性",
             lambda: page.url),
            ("screenshot(full_page=True)  ★每章都调",
             lambda: page.screenshot(
                 path=os.path.join(DIAG_DIR, "_shot_probe.png"),
                 full_page=True)),
            ("screenshot(full_page=False)",
             lambda: page.screenshot(
                 path=os.path.join(DIAG_DIR, "_shot_probe2.png"),
                 full_page=False)),
        ):
            for _ in range(4):
                raw(label, fn)

        # ---------------------------------------------------- 阶段 3
        hr("#")
        say("#  阶段 3：★ 完整「一章」的 UI 全流程")
        say("#         （续写弹窗 + 审稿抽屉，全程不点生成 → 零额度消耗）")
        hr("#")

        PLOT = ("诊断用占位剧情，不会被提交（本脚本绝不点生成）。"
                "主角在雨夜拿到了关键证据，为下一章的反转埋下伏笔。")
        REQ = "强盛集团云霄拯救过稿计划"
        INSTR = "请按爽文节奏审改以下正文，重点检查毒点与逻辑断裂。"

        round_times: list[float] = []
        for rnd in (1, 2, 3):
            hr()
            say(f"  ◆◆◆ 第 {rnd} 轮：完整走一遍「一章」的 UI 操作")
            hr()
            t0 = REAL_PERF()

            # ---------- 阶段一：续写弹窗 ----------
            t = REAL_PERF()
            if not AI.open_continue_dialog(page, wait=3.0):
                say(f"  [轮 {rnd}] ✗ 续写弹窗未打开")
                break
            say(f"  [轮 {rnd}]   ① 开续写弹窗        {REAL_PERF()-t:6.2f}s")

            if rnd == 1:
                dump_dom(page, f"r{rnd}-opened")

            t = REAL_PERF()
            AI.select_model(page, model="细腻版", associate="正常")
            say(f"  [轮 {rnd}]   ② 选模型(细腻版)    {REAL_PERF()-t:6.2f}s"
                f"   当前={AI.current_model(page)!r}")

            t = REAL_PERF()
            AI.fill_plot(page, PLOT)
            say(f"  [轮 {rnd}]   ③ 填后续剧情        {REAL_PERF()-t:6.2f}s")

            t = REAL_PERF()
            r_rel = AI.relate_chapters(page, 10)
            say(f"  [轮 {rnd}]   ④ 关联最近10章      {REAL_PERF()-t:6.2f}s"
                f"   = {r_rel}   当前档位="
                f"{AI.current_relate_count(page)}")

            t = REAL_PERF()
            AI._shot(page, f"diag_ready_{rnd}")     # 每章都会截这一张
            say(f"  [轮 {rnd}]   ⑤ 截图 ai_ready     {REAL_PERF()-t:6.2f}s")

            t = REAL_PERF()
            AI.close_continue_dialog(page)
            say(f"  [轮 {rnd}]   ⑥ 关续写弹窗        {REAL_PERF()-t:6.2f}s")

            # ---------- 阶段三：审稿抽屉 ----------
            t = REAL_PERF()
            AI.open_review_pane(page)
            say(f"  [轮 {rnd}]   ⑦ 开审稿抽屉        {REAL_PERF()-t:6.2f}s")

            t = REAL_PERF()
            AI.pick_review_requirement(page, keyword=REQ)
            say(f"  [轮 {rnd}]   ⑧ 选审稿要求        {REAL_PERF()-t:6.2f}s")

            t = REAL_PERF()
            AI.fill_review_text(page, instruction=INSTR)
            say(f"  [轮 {rnd}]   ⑨ 填待审文本        {REAL_PERF()-t:6.2f}s")

            t = REAL_PERF()
            AI.select_all_body(page)
            say(f"  [轮 {rnd}]   ⑩ 全选正文          {REAL_PERF()-t:6.2f}s")

            t = REAL_PERF()
            AI.close_review_pane(page)
            say(f"  [轮 {rnd}]   ⑪ 关审稿抽屉        {REAL_PERF()-t:6.2f}s")

            el = REAL_PERF() - t0
            round_times.append(el)
            hr("-")
            say(f"  [轮 {rnd}] ★ 单章 UI 开销合计 = {el:.2f}s "
                f"（不含任何 AI 生成时间）")
            hr()

        if round_times:
            hr("#")
            say(f"#  ★ 单章 UI 开销：平均 "
                f"{sum(round_times)/len(round_times):.2f}s   "
                f"各轮 {[round(x, 2) for x in round_times]}")
            hr("#")

        # ---------------------------------------------------- 报告
        table_fn("A. 函数耗时归因（真实浏览器）")
        table_sleep("B. 固定 sleep 归因（剩余的白等）")
        table_waits("C. 条件等待明细（轮询效率）")
        table_raw("D. 浏览器原始操作往返成本")

        hr("#")
        say("#  结论汇总")
        hr("#")
        say(f"  总 sleep 白等      : {sum(s[2] for s in SLEEPS):.2f}s "
            f"（{len(SLEEPS)} 次）")
        say(f"  条件等待总耗时     : {sum(w['elapsed'] for w in WAITS):.2f}s "
            f"（{len(WAITS)} 次，"
            f"{sum(w['polls'] or 0 for w in WAITS)} 次轮询）")
        say(f"  原始操作平均往返   : "
            f"{sum(r[1] for r in RAW)/max(1,len(RAW))*1000:.1f}ms "
            f"（{len(RAW)} 次采样）")
        hr("#")

    except Exception as e:
        import traceback
        say("\n!!! 诊断异常 !!!")
        say(traceback.format_exc())
        return 2
    finally:
        if app is not None:
            try:
                app.stop()
            except Exception:
                pass
        _out.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())

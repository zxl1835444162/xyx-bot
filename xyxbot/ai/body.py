"""正文编辑器与字数统计。

本文件由 `xyxbot/ai.py` 拆分而来（Phase C1）。拆分时按 AST 依赖做了拓扑排序，
所以每个模块只 import 排在自己前面的模块，不存在循环引用。
"""

from __future__ import annotations

from xyxbot.waiting import wait_gone, wait_until, wait_visible
from playwright.sync_api import Page
import re
import time

from xyxbot.ai.current import _text_of
from xyxbot.ai.elements import _safe_click, _shot
from xyxbot.ai.selectors import AI_SELECTORS

__all__ = ["_parse_word_num", "_selection_len", "chapter_word_count", "count_chars", "editor_ready", "get_body_text", "select_all_body", "site_chapter_word_count", "wait_body_change"]

def editor_ready(page: Page,
                 need_text: bool = False) -> bool:
    """正文编辑器是否已就绪（有 .tiptap.ProseMirror 且可见）。

    Args:
        need_text: ★ True 时要求**正文非空**才算就绪。
                   实测（2026-10-03）：进编辑器后 `.tiptap.ProseMirror`
                   **一直存在**（空壳），所以只判存在会误判「已就绪」，
                   结果待审文本是空的。需要「真有内容」的场景要传 True。
    """
    for sel in AI_SELECTORS["editor_body"]:
        try:
            loc = page.locator(sel).first
            if not (loc.count() and loc.is_visible()):
                continue
            if need_text and not get_body_text(page).strip():
                continue
            return True
        except Exception:
            continue
    return False

def get_body_text(page: Page) -> str:
    """读正文编辑器里的纯文本。

    ★★ 注意（2026-10-06）：这个返回值的 `len()` **不等于站点显示的「字数」**！
      `.tiptap.ProseMirror` 的 `innerText` 会给**每个段落**补一个换行，
      所以 len() 比站点那个数**虚高 16%~27%**（实测见 `count_chars` 的说明）。
      凡是要**展示/上报字数**，一律用 `chapter_word_count(page)`，
      不要直接 `len(get_body_text(page))`。
    """
    try:
        return page.evaluate("""() => {
          const ed = document.querySelector('.tiptap.ProseMirror')
                     || document.querySelector("div[contenteditable='true']");
          return ed ? (ed.innerText || '') : '';
        }""") or ""
    except Exception:
        return ""

def count_chars(text: str) -> int:
    """按**站点口径**数「字数」：空白不计（换行 / 空格 / 全角空格都不算）。

    ★★ 为什么不用 `len(text)`（2026-10-06，探针 `probes/probe_wc_site.py` 实测）：

      用户报「高级参数里认到的字数不准确」。真机取证 —— 同一章「第3章」：
        · 站点左栏 `.chapter-item__meta`      = 「4,018 字」
        · 站点编辑器右下 `.chapter-word-count` = 「4018」      ← 站点的权威数字
        · app `len(get_body_text(page))`      = **4676**       ← ❌ 界面结果表用的
        · app 去掉空白后                       = 4036
        其中 `\\n` 有 **629** 个 —— 虚高 **658 字（+16.4%）**。第 1 章更夸张：
        站点 15,676 vs app 20,027（**+27%**）。

      生成结果弹窗同样：站点显示 3422，而 textarea 的 `.value` 长 3540，
      差的 118 正好是段落换行 ⇒ **站点口径 = 非空白字符数**。

      ⇒ 所以「字数」必须把空白剔掉，才对得上用户在站点上看到的数字。
    """
    if not text:
        return 0
    return sum(1 for ch in text if not ch.isspace())

def _parse_word_num(s: str) -> int:
    """把站点上的字数文本解析成 int。

    兼容：'4018' / '4,018 字' / '2.1万字' / '1.2千字' / '1,234'
    """
    if not s:
        return -1
    t = s.strip().replace(",", "").replace("，", "")
    m = re.search(r"(\d+(?:\.\d+)?)\s*万", t)
    if m:
        return int(float(m.group(1)) * 10000)
    m = re.search(r"(\d+(?:\.\d+)?)\s*千", t)
    if m:
        return int(float(m.group(1)) * 1000)
    m = re.search(r"\d+", t)
    if m:
        return int(m.group(0))
    return -1

def site_chapter_word_count(page: Page) -> int:
    """读**站点自己显示的**本章字数（用户对照的那个数）。读不到返回 -1。

    ① 编辑器右下角 `.chapter-word-count`（实测文本就是纯数字，如 "4018"）
    ② 左栏**当前章**的 `.chapter-item__meta`（实测形如 "4,018 字"）

    ★ 为什么优先读站点：这是用户眼睛看到的数字，读它**永远不会对不上**。
      自己在本机算总有口径差（站点还会排掉 ProseMirror 的分章标记等）。
    """
    # ① 编辑器右下角的实时字数
    try:
        loc = page.locator(".chapter-word-count")
        for i in range(min(loc.count(), 3)):
            it = loc.nth(i)
            try:
                if not it.is_visible():
                    continue
                v = _parse_word_num(_text_of(it, timeout=300) or "")
                if v > 0:
                    return v
            except Exception:
                continue
    except Exception:
        pass

    # ② 左栏当前（active）章的字数
    for sel in (".chapter-item--active .chapter-item__meta",
                "[class*=chapter-item][class*=active] .chapter-item__meta",
                ".chapter-item__meta"):
        try:
            loc = page.locator(sel)
            if not loc.count():
                continue
            v = _parse_word_num(_text_of(loc.first, timeout=300) or "")
            if v > 0:
                return v
        except Exception:
            continue
    return -1

def chapter_word_count(page: Page, body: str | None = None) -> int:
    """**本章字数**（统一口径，展示/上报一律用这个）。

    优先「站点自己显示的数」；站点读不到时退回「非空白字符数」
    （与站点口径一致，实测误差 < 1%）。
    """
    v = site_chapter_word_count(page)
    if v > 0:
        return v
    return count_chars(body if body is not None else get_body_text(page))

def select_all_body(page: Page, verify: bool = True) -> bool:
    """★ 全选正文编辑器里的内容。

    ★ 为什么必须全选（用户要求）：
        审稿生成的「替换 / 插入」是**智能双模**——
          有选中 → **替换**选中内容
          没选中 → 光标处**插入**
        不全选的话，结果会**插在原稿前面**，原稿还留着（前后拼接）。

    ★ 实测两条路都行（都能选中 106 字全文）：
        ① 点工具栏 `button[aria-label='全选']`  ← 首选
        ② 编辑器聚焦后 `Ctrl+A`                ← 兜底

    Args:
        verify: 是否校验选区（True 时读 selection 长度）
    """
    print("[ai] --- 全选正文 ---")

    def _selected(timeout: float) -> bool:
        """★ 条件等待「选区真的出现」，替代原来的固定 sleep 0.8s。

        选区是浏览器**瞬时**状态，点完立刻就能读到；原来固定等 0.8 秒
        纯属白等。这里高频轮询，通常 1~2 次就返回。
        """
        if not verify:
            # 不校验时也要给一点点时间让点击生效（避免紧接着的替换读到旧选区）
            time.sleep(0.15)
            return True
        return wait_until(lambda: _selection_len(page) > 0,
                          timeout=timeout, interval=0.05,
                          desc="全选生效").ok

    # ① 点「全选」按钮（aria-label，★ 不是 title！踩过坑）
    for sel in AI_SELECTORS["btn_editor_select_all"]:
        try:
            b = page.locator(sel).first
            if b.count() and b.is_visible():
                # ★ 短超时 + JS 降级：残留遮罩会让原生点击白等满 4 秒
                #   （实测该步骤 4.21 秒/章，改完约 0.1 秒）
                _safe_click(b, label="全选")
                if _selected(2.5):
                    print(f"[ai] ✓ 已全选（按钮 {sel}）")
                    return True
                print("[ai] ⚠ 点了「全选」但没选中，试 Ctrl+A")
                break
        except Exception as e:
            print(f"[ai] ⚠ 点「全选」失败：{str(e).splitlines()[0]}")
            continue

    # ② 兜底：聚焦编辑器 + Ctrl+A
    try:
        page.evaluate("""() => {
          const ed = document.querySelector('.tiptap.ProseMirror')
                     || document.querySelector("div[contenteditable='true']");
          if (ed) { ed.focus(); }
        }""")
        # 等编辑器真的拿到焦点（原来是固定 sleep 0.3）
        wait_until(lambda: page.evaluate(
            "() => !!document.activeElement && "
            "(document.activeElement.isContentEditable "
            "|| document.activeElement.tagName === 'DIV')"),
            timeout=1.5, interval=0.05, desc="编辑器聚焦")
        page.keyboard.press("Control+a")
        if _selected(2.0):
            n = _selection_len(page)
            print(f"[ai] ✓ 已全选（Ctrl+A，选区 {n} 字）")
            return True
        print("[ai] ✗ Ctrl+A 也没选中")
    except Exception as e:
        print(f"[ai] ✗ Ctrl+A 失败：{str(e).splitlines()[0]}")

    _shot(page, "ai_select_all_failed")
    return False

def _selection_len(page: Page) -> int:
    """当前选区长度（字符数）。"""
    try:
        return int(page.evaluate(
            "() => { const s = window.getSelection();"
            " return s ? s.toString().length : 0; }") or 0)
    except Exception:
        return 0

def wait_body_change(page: Page, before_len: int = -1,
                     timeout: float = 20.0, poll: float = 1.0,
                     before_words: float | None = None) -> int:
    """★ 等正文真正写入编辑器（采纳之后）。

    ★ 为什么要等：点了「采纳使用」≠ 正文立刻就在编辑器里。
      Naive UI 弹窗关闭 + 编辑器重渲染有延迟，
      不等的话下一环节（审稿）可能读到**空正文或旧正文**。

    Args:
        before_len:   采纳前的**原始正文长度**（`len(get_body_text())`，含换行）
                      —— 只用它做「变了没」的判据（最灵敏，不受口径影响）；
                      -1 = 不比较，只要非空就算好
        timeout:      最多等多久
        before_words: 采纳前的**展示用字数**（站点口径）。只影响日志文案
                      （`None` = 沿用 before_len，保持旧行为）

    Returns:
        int 最终正文**字数（站点口径）**——超时则返回当前值。
        ★★ 2026-10-06：返回值从「含换行的原始长度」改成「站点口径字数」，
          因为它会一路传到界面结果表的「字数」列。老口径实测虚高 16%~27%。
    """
    _bw = before_len if before_words is None else int(before_words)
    print(f"[ai] --- 等正文写入（采纳前 {_bw} 字）---")
    last = [-1]
    # ★ 效率改造：原实现是「先 sleep(poll=1.0) 再检查」→ 条件早就满足也要
    #   白等 1 秒，且粗轮询让最坏情况再多等 1 秒。
    #   现在改为**先检查后等待**、并把轮询降到 0.1s：
    #   正文已经写好时立刻返回（≈0 秒），没写好也是 0.1s 粒度跟进。
    def _cond():
        cur = len(get_body_text(page))      # ★ 判据仍用原始长度（最灵敏）
        if cur != last[0]:
            # ★ 日志展示用站点口径 —— 与用户在站点上看到的数字一致
            print(f"[ai]   正文当前 {chapter_word_count(page)} 字")
            last[0] = cur
        return cur if (cur > 0 and (before_len < 0 or cur != before_len)) else None

    res = wait_until(_cond, timeout=timeout, interval=0.1, desc="正文写入")
    if res.ok:
        # ★★ 站点那个「本章字数」是 Vue 计算属性，可能有极短的刷新延迟。
        #    这里用「连续两次读数一致」判定它已经稳定，最多等 1.5s
        #    （等不到也用当前值，不阻塞流程）。
        final = -1
        try:
            _last = [None]
            _stable = [0]

            def _settled() -> bool:
                v = site_chapter_word_count(page)
                if v <= 0:
                    return False
                if v == _last[0]:
                    _stable[0] += 1
                else:
                    _last[0] = v
                    _stable[0] = 0
                return _stable[0] >= 1

            wait_until(_settled, timeout=1.5, interval=0.15, desc="站点字数刷新")
            if _last[0] and _last[0] > 0:
                final = int(_last[0])
        except Exception:
            pass
        if final <= 0:
            final = chapter_word_count(page)
        if final <= 0:
            final = count_chars(get_body_text(page))
        print(f"[ai] ✓ 正文已更新：{_bw} → {final} 字")
        return int(final)
    # ★ 超时：沿用旧语义 —— 返回**当前**字数（读不到就是 0），
    #   让上层按"正文为空"判定失败，而不是返回 -1 显示成「-1 字」。
    _cur = chapter_word_count(page)
    print(f"[ai] ⚠ 等正文写入超时（当前 {_cur} 字）")
    return int(_cur) if _cur > 0 else 0

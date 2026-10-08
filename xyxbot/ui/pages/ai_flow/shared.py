"""四个入口共用的步骤（校验作品 / 渲染剧情 / 读参数 / 准备登录态 / 打开作品）。

由 `xyxbot/ui/main_window.py` 拆分而来（class split）：只搬位置、
不改逻辑（方法体、注释、装饰器、超时值全部原样）。
"""

from __future__ import annotations

from xyxbot.ui.defaults import (
    DEFAULT_MAX_RETRY,
    DEFAULT_MAX_WORDS,
    DEFAULT_MIN_WORDS,
    DEFAULT_REVIEW_ASSOCIATE,
    DEFAULT_REVIEW_CARD,
    DEFAULT_REVIEW_MODEL,
    DEFAULT_REVIEW_TAB,
    DEFAULT_REVIEW_TIMEOUT,
)


class AiFlowSharedMixin:
    """四个入口共用的步骤（校验作品 / 渲染剧情 / 读参数 / 准备登录态 / 打开作品）。"""

    # -------------------------------------------------- 共用步骤

    def _ai_book_ok(self):
        """校验「作品名称」并解析 --index。返回 (book, 有没有指定第几本) 或 None。"""
        book = self._ai_book_entry.get().strip()
        if not book:
            self.log("请填写「作品名称」（站点上那本书的名字）", "warn")
            return None
        _idx, ok = self._parse_book_index()
        if not ok:
            return None
        return book

    def _ai_render_plot(self):
        """把「指令模板」渲染成这次要投喂的剧情文本。返回 (plot, 用到的代号) 或 None。

        ★★ 根因修复（保留）：原来没传 `current=` → 模板里的 `#@`（以及
          {{当前章}}/{{本章}}/#当前章）会**原样**送进站点，而 UI 文案一直在教用户
          「#@ = 当前章」。现在按「续写到第几章」下拉解析当前章。
        """
        if self._project is None:
            self.log("还没有分章，先选文件分章", "warn")
            return None
        self._collect_notes()
        self._project.instruction = self._get_instruction()
        tpl = self._project.instruction
        if not tpl:
            self.log("「指令模板」是空的，先写点什么（比如 #1）", "warn")
            return None
        chk = self._project.check_template(tpl)
        if chk["unknown"]:
            self.log("✗ 指令里有不存在的代号："
                     + " ".join(f"#{n}" for n in chk["unknown"])
                     + f"（共 {len(self._project.chapters)} 章）", "err")
            return None
        if chk["empty"]:
            self.log("⚠ 这些章还没填细纲，会用原文兜底："
                     + " ".join(f"#{n}" for n in chk["empty"]), "warn")
        cur_no = self._resolve_current_chapter_no()
        if cur_no is not None and self._project.CUR_RE.search(tpl):
            self.log(f"[ai] 「当前章」占位符 → 第{cur_no}章", "info")
        plot = self._project.render_template(tpl, current=cur_no)
        if not plot.strip():
            self.log("指令模板渲染出来是空的，检查一下 #N 写对没", "err")
            return None
        self._set_preview(plot, f"✓ 待发送（{len(plot)} 字）")
        used = " ".join(f"#{n}" for n in chk["used"]) or "（无代号）"
        return plot, used

    def _ai_gen_opts(self):
        """续写参数（快捷选项 / 自动采纳 / 字数区间 / 重试次数）。

        ★★ 修正（2026-10-04 用户报「2700 字竟然过了 2100-2300 的限制」）：
           原实现把区间写死成 100~5000、重试硬编码 0，理由是「让字数限制宽一点，
           避免重试」—— 两者叠加 = **字数限制完全失效**（任何字数都算达标）。
           现在严格使用界面上的区间与重试次数。
        """
        shortcut = self._ai_shortcut_entry.get().strip()     # 读取顺序与原实现一致
        auto_accept = bool(self._ai_auto_var.get())
        min_words = _int_or(self._ai_min_entry, DEFAULT_MIN_WORDS)
        max_words = _int_or(self._ai_max_entry, DEFAULT_MAX_WORDS)
        max_retry = _int_or(self._ai_retry_entry, DEFAULT_MAX_RETRY)
        if min_words > max_words:
            if auto_accept:
                self.log(f"字数区间写反了（{min_words}~{max_words}），已自动交换", "warn")
            min_words, max_words = max_words, min_words
        return {"shortcut": shortcut,
                "auto_accept": auto_accept,
                "min_words": min_words, "max_words": max_words,
                "max_retry": max_retry}

    def _ai_review_opts(self):
        """审稿参数（模型 / 联想 / 要求 / 追加指令 / 先开章节 / 替换 / 超时）。

        读取顺序与原实现保持一致（纯读界面，无副作用，但顺序变了会让
        tools/dev/flow_equiv.py 的比对出现无意义差异）。
        """
        model = self._rv_model_entry.get().strip() or DEFAULT_REVIEW_MODEL
        card = self._rv_card_entry.get().strip() or DEFAULT_REVIEW_CARD
        assoc = self._rv_assoc_entry.get().strip() or DEFAULT_REVIEW_ASSOCIATE
        req = self._rv_req_entry.get().strip()
        # ★★ 追加指令（待审文本是自带章节正文的，这里再补一段提示词）
        instruction = self._rv_instr_text.get("1.0", "end").strip()
        # ★ 先打开章节
        chapter = self._rv_chapter_entry.get().strip()
        # ★ 审稿流程开关（放在 chapter 与 replace 之间，与原实现的读取顺序一致）
        wait_done = bool(self._rv_wait_var.get())
        replace = bool(self._rv_replace_var.get())
        select_all = bool(self._rv_select_all_var.get())
        tout = self._rv_timeout_entry.get().strip()
        timeout = int(tout) if tout.isdigit() else DEFAULT_REVIEW_TIMEOUT
        return {"model": model, "card": card, "assoc": assoc, "req": req,
                "instruction": instruction, "chapter": chapter,
                "wait_done": wait_done,
                "replace": replace, "select_all": select_all,
                "timeout": timeout}

    def _ai_prepare_session(self):
        """阶段零：没登录态就先做「打开网站 + 保存 cookie/缓存」。返回 (能否继续, 失败原因)。

        ★ 只在**没有**登录态时做，已有则跳过（不打断用户节奏）。
        """
        from xyxbot import login as L

        st = L.is_ready()
        if st["ok"]:
            self.after(0, self.log, f"已有登录态，跳过准备（{st['age']}）", "dim")
            return True, ""
        self.after(0, self.log, "尚未准备：先打开网站并保存登录态…", "warn")
        pr = L.prepare_session(self._app, save=True, auto=True,
                               wait_seconds=0, interactive=True)
        if not pr["ok"]:
            return False, f"准备未完成：{pr['message']}"
        self.after(0, self.log, "✓ 准备就绪", "ok")
        self.after(0, self._prepare_refresh)
        return True, ""

    def _ai_open_book(self, page, book):
        """在浏览器里打开作品（worker 线程内调用）。失败返回 False。"""
        from xyxbot import books as B

        self.after(0, self.log, f"打开作品《{book}》…", "brand")
        if not B.open_book(page, book, console_pick=False,
                           index=self._ai_book_index, wait=3.0):
            return False
        self.after(0, self.log, "✓ 已进入作品编辑器", "ok")
        return True


def _int_or(entry, default: int) -> int:
    """从输入框读整数，读不到（空/非数字）就用默认值。

    原本这个函数在三个入口里各定义了一份，现在收成模块级一个。
    """
    text = entry.get().strip()
    return int(text) if text.isdigit() else default

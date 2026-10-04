"""分章、章节列表、指令模板、章节菜单与工程存取。

从 ui/main_window.py 拆出的独立模块（架构改良阶段二）。

内容包含四块：
  * 分章：选文件 → NovelProject.load → 渲染章节列表（细纲输入框）
  * 指令模板：读写 _tpl_text、实时预览、代号校验
  * 章节菜单：_refresh_ai_chapter_menu / _current_ai_chapter /
    _resolve_current_chapter_no（#@ 当前章解析）/ _parse_book_index
  * 工程存取：.novel.json 的另存与打开、细纲回写

★ 依赖（由 MRO 解析）：_on_mousewheel（窗口滚动）、_save_ws（config_io）。
"""

from __future__ import annotations

import threading
import tkinter as tk
from pathlib import Path

from ..defaults import (
    DEFAULT_MAX_RETRY,
    DEFAULT_MAX_WORDS,
    DEFAULT_MIN_WORDS,
    DEFAULT_REVIEW_ASSOCIATE,
    DEFAULT_REVIEW_CARD,
    DEFAULT_REVIEW_MODEL,
    DEFAULT_REVIEW_TAB,
    DEFAULT_REVIEW_TIMEOUT,
)
from ..theme import COLOR, F, DarkEntry


class ChaptersMixin:
    """分章与章节资产管理。"""

    def _ch_scroll(self, event):
        """章节列表内部滚动。

        ★ 嵌套滚动处理：列表滚到顶/底后，把剩余滚动交给整页外层，
          这样鼠标停在列表上也能顺畅继续往下翻页。
        """
        delta = int(-event.delta / 120)
        try:
            first, last = self._ch_canvas.yview()
            at_top = first <= 0.0
            at_bottom = last >= 1.0
            if (delta < 0 and at_bottom) or (delta > 0 and at_top):
                # 交给外层整页滚动
                self._on_mousewheel(event)
                return "break"
            self._ch_canvas.yview_scroll(delta, "units")
        except Exception:
            pass
        return "break"

    # -------------------------------------------------- 选文件 / 分章

    def _pick_novel(self):
        """文件对话框选 txt —— 通用入口，不写死路径。"""
        from tkinter import filedialog

        p = filedialog.askopenfilename(
            title="选择小说 txt 文件",
            filetypes=[("文本文件", "*.txt"), ("所有文件", "*.*")],
            initialdir=str(Path.home() / "Desktop"),
        )
        if p:
            self._novel_entry.set(p)
            self.log(f"已选择文件：{p}", "info")
            self._do_split()          # 选完直接分章，省一次点击

    def _do_split(self):
        """后台线程分章。"""
        import threading

        path = self._novel_entry.get().strip().strip('"')
        if not path:
            self._split_hint.config(text="请先选择一份 .txt 小说文件")
            self.log("请先选择小说文件", "warn")
            return
        if not Path(path).exists():
            self._split_hint.config(text=f"文件不存在：{path}")
            self.log(f"文件不存在：{path}", "err")
            return

        self.log(f"正在分章：{path} …", "brand")
        self.status.set_status("分章中…", "warn")
        self._split_hint.config(text="正在读取并分章…")

        # ★ 线程安全：tk 控件只能在主线程读，先把前后缀取值出来再进 worker。
        #   原实现在 worker 里调 self._prefix_entry.get()（跨线程碰 Tk）。
        _pre = ""
        _suf = ""
        try:
            _pre = self._prefix_entry.get().strip()
            _suf = self._suffix_entry.get().strip()
        except Exception:
            pass

        def worker():
            try:
                from src.novel import NovelProject

                proj = NovelProject.load(path)
                proj.global_prefix = _pre
                proj.global_suffix = _suf

                if not proj.chapters:
                    self.after(0, lambda: self._split_hint.config(
                        text="没能识别出任何章节，请检查文件格式"
                             "（需含「第X章」标题）"))
                    self.after(0, self.log, "分章失败：未识别到章节", "err")
                    return

                self._project = proj
                total = len(proj.chapters)
                # ★ 分章成功 → 自动记住这次的文件（下次免选）
                self.after(0, self._save_ws, True)
                # ★★ 同时存一份「轻量记忆」——下次启动直接恢复，不用再分章
                self.after(0, self._save_last_project)
                self.after(0, self._render_chapters)
                self.after(0, lambda: self._split_hint.config(
                    text=f"✓ 《{proj.name}》共 {total} 章，"
                         f"每章一个短代号 #1 #2 …，可在下方填写细纲"))
                self.after(0, self.log,
                           f"分章完成：《{proj.name}》 {total} 章", "ok")
                self.after(0, self.status.set_status, f"已分 {total} 章", "ok")
                # 预览前 5 个短代号
                for t in proj.tokens()[:5]:
                    self.after(0, self.log, f"    短代号 {t}", "info")
                if total > 5:
                    self.after(0, self.log, f"    … 共 {total} 个", "info")
            except Exception as e:
                self.after(0, lambda: self._split_hint.config(
                    text=f"分章失败：{e}"))
                self.after(0, self.log, f"分章异常：{e}", "err")

        threading.Thread(target=worker, daemon=True).start()

    def _render_chapters(self):
        """把章节渲染成「占位符 + 输入框」列表。"""
        for w in self._ch_list.winfo_children():
            w.destroy()
        self._ch_entries.clear()

        proj = self._project
        if proj is None:
            return

        self._ch_head.config(text=f"章节列表（{len(proj.chapters)} 章）")
        self._ch_info.config(text="每行填这一章的细纲，写指令时用它的代号 #N 引用")

        for c in proj.chapters:
            box = tk.Frame(self._ch_list, bg=COLOR["bg_card_hi"],
                           highlightbackground=COLOR["border"],
                           highlightthickness=1)
            box.pack(fill="x", pady=3, padx=1)

            inner = tk.Frame(box, bg=COLOR["bg_card_hi"])
            inner.pack(fill="x", padx=12, pady=9)

            # 第一行：★ 短代号 + 章节标题
            top = tk.Frame(inner, bg=COLOR["bg_card_hi"])
            top.pack(fill="x")
            # 代号带底色，像标签一样
            tag = tk.Label(top, text=f" {c.code} ", font=F(9, True),
                           bg=COLOR["brand"], fg=COLOR["text_on_brand"],
                           padx=4, pady=1)
            tag.pack(side="left")
            tk.Label(top, text=c.title, font=F(9), bg=COLOR["bg_card_hi"],
                     fg=COLOR["text_dim"]).pack(side="left", padx=(10, 0))
            tk.Label(top, text=f"{len(c.body)} 字原文", font=F(8),
                     bg=COLOR["bg_card_hi"],
                     fg=COLOR["text_mute"]).pack(side="right")

            # 第二行：输入框（填细纲）
            e = DarkEntry(inner, placeholder=f"填写这一章的细纲，之后用 {c.code} 引用…",
                          icon="✎", width=700, height=36)
            e.pack(fill="x", pady=(6, 0))
            if c.note:
                e.set(c.note)
            self._ch_entries[c.no] = e

        # 同步「一键续写」的章节下拉
        self._refresh_ai_chapter_menu()
        # 刷新指令模板里的代号提示与预览
        self._update_code_hint()
        self._update_tpl_preview()

    # -------------------------------------------------- ★ 指令模板

    def _set_tpl(self, tpl: str):
        """写入指令模板。"""
        self._tpl_text.delete("1.0", "end")
        self._tpl_text.insert("1.0", tpl)
        self._update_tpl_preview()

    def _get_instruction(self) -> str:
        return self._tpl_text.get("1.0", "end").strip()

    def _update_code_hint(self):
        """在指令模板卡里提示 #1 #2 … 分别对应哪一章。"""
        proj = self._project
        if proj is None:
            self._code_hint.config(text="（分章后这里显示 #1 #2 … 对应哪几章）")
            return
        parts = [f"{c.code}={c.title.split(' ', 1)[-1][:8] if ' ' in c.title else c.title[:8]}"
                 for c in proj.chapters[:4]]
        more = f" … 共 {len(proj.chapters)} 章" if len(proj.chapters) > 4 else ""
        self._code_hint.config(text="代号：" + "  ".join(parts) + more)

    def _toggle_wrap(self):
        """显示/隐藏统一前后缀输入行。"""
        wr = self._wrap_widgets[0]
        if self._use_wrap.get():
            wr.pack(fill="x", pady=(6, 0))
        else:
            wr.pack_forget()

    def _update_tpl_preview(self):
        """把指令模板里的 #N 替换掉，实时预览。"""
        if not hasattr(self, "_tpl_preview"):
            return
        proj = self._project
        txt = self._get_instruction()
        if proj is None:
            self._set_preview("（先分章，然后这里会显示替换结果）", "")
            return
        if not txt:
            self._set_preview("（指令模板是空的，点上面的快捷按钮或自己写）", "")
            return

        # 回写输入框内容，保证预览用的是最新细纲
        self._collect_notes()
        proj.instruction = txt
        # 前后缀（勾选才带）
        if self._use_wrap.get():
            proj.global_prefix = self._prefix_entry.get().strip()
            proj.global_suffix = self._suffix_entry.get().strip()

        # ★ 预览也要传 current，否则 #@ 在预览里原样显示（与实际发送不一致）
        out = proj.render_template(current=self._resolve_current_chapter_no())
        chk = proj.check_template()
        msg = ""
        if chk["unknown"]:
            msg = "✗ 有没定义的代号：" + " ".join(f"#{n}" for n in chk["unknown"])
        elif chk["empty"]:
            msg = "⚠ 这些章还没填细纲：" + " ".join(f"#{n}" for n in chk["empty"])
        else:
            msg = f"✓ OK（{len(out)} 字）"
        self._set_preview(out, msg)

    def _set_preview(self, text: str, state_msg: str):
        try:
            self._tpl_preview.configure(state="normal")
            self._tpl_preview.delete("1.0", "end")
            self._tpl_preview.insert("1.0", text)
            self._tpl_preview.configure(state="disabled")
            if state_msg:
                color = "ok" if state_msg.startswith("✓") else (
                    "warn" if state_msg.startswith("⚠") else "err")
                self._tpl_state.config(text=state_msg, fg=COLOR.get(color, COLOR["text_dim"]))
            else:
                self._tpl_state.config(text="")
        except Exception:
            pass

    # -------------------------------------------------- 一键 AI 续写

    def _refresh_ai_chapter_menu(self):
        """分章/载入工程后，重建「要续写的章节」下拉。"""
        menu = self._ai_ch_menu["menu"]
        menu.delete(0, "end")
        proj = self._project
        if proj is None:
            menu.add_command(label="（先分章）", command=lambda: None)
            self._ai_ch_var.set("（先分章）")
            return
        for c in proj.chapters:
            label = f"{c.code} {c.title}"[:40]
            menu.add_command(label=label,
                             command=lambda l=label: self._ai_ch_var.set(l))
        first = proj.chapters[0]
        self._ai_ch_var.set(f"{first.token} {first.title}"[:40])

    def _current_ai_chapter(self):
        """从下拉的当前值解析出 Chapter。

        ★ 下拉 label 形如 "#3 第3章 标题"，取开头的 #N 去查。
        """
        if self._project is None:
            return None
        label = self._ai_ch_var.get() or ""
        import re as _re
        m = _re.match(r"\s*#\s*(\d+)", label)
        if not m:
            # 兜底：也认 {{第N章}} / 第N章
            m = (_re.match(r"\s*\{\{第(\d+)章\}\}", label)
                 or _re.match(r"\s*第(\d+)章", label))
        if m:
            return self._project.find(m.group(1))
        return None

    def _resolve_current_chapter_no(self):
        """解析「当前章」章号，供 `render_template(current=...)` 用。

        优先级：
          ① 「续写到第几章」下拉里选中的章
          ② 没选 → 取最小章号（与 `ai_auto_chapter` 的兜底策略保持一致：
             绝不切到「最新章」，否则会出现「第1章的内容写进第4章」）
          ③ 工程为空 → None（此时 `#@` 无法解析）

        返回 int 或 None。
        """
        proj = self._project
        if proj is None or not proj.chapters:
            return None
        cur = self._current_ai_chapter()
        if cur is not None:
            return cur.no
        try:
            return min(c.no for c in proj.chapters)
        except Exception:
            return None

    def _parse_book_index(self):
        """★ 解析「第几本」输入框（同名多本时的序号，从 0 开始）。

        返回 `(index, ok)`：
          - 留空        → (None, True)   表示不限，交给 `open_book` 判断
          - 合法数字    → (int, True)
          - 非法        → (None, False)  调用方应中止并提示

        ★ 根因修复：原本 `_ai_go` / `_ai_review_go` / `_ai_both_go` 各自内联
          解析并写进 `self._ai_book_index`，但 **`_ai_batch_go` 从不解析**
          却直接使用该字段 → 批量跑章会用到上一次单章操作留下的**陈旧索引**，
          可能打开错误的同名作品。现在统一走这个helper，四处行为一致。
        """
        from tkinter import TclError

        try:
            txt = self._ai_idx_entry.get().strip()
        except TclError:
            return (None, True)
        if not txt:
            self._ai_book_index = None
            return (None, True)
        if txt.lstrip("-").isdigit():
            self._ai_book_index = int(txt)
            return (self._ai_book_index, True)
        # ★ 非法输入：把状态清掉，避免残留上一次的索引被后续流程误用
        self._ai_book_index = None
        self.log("「第几本」只能填数字（从 0 开始）", "warn")
        return (None, False)

    # ★★ 2026-10-04 界面重设计：这里原有 ~610 行 AI 流程方法
    #   （_ai_go / _ai_review_go / _ai_both_go / _ai_batch_go 及其
    #    on_* 回调），但它们是**拆分阶段留下的副本且已过期**。
    #   实测 MRO：MainWindow._ai_batch_go.__qualname__
    #            == 'AiFlowMixin._ai_batch_go'
    #   → 实际生效的一直是 ai_flow.py 里的版本，这一整块从未被执行。
    #   为了不再出现「同一功能两份实现、改了其中一份却不生效」的坑，
    #   已删除。要改 AI 流程请改 ui/pages/ai_flow.py。

    # -------------------------------------------------- 保存 / 读取工程

    # ★★ 轻量记忆（2026-10-04 用户需求："上次填的，下次不用重填"）
    #
    #   和「另存工程 / 打开工程」的区别：
    #     * 另存工程  —— 显式的、带文件名的、含小说正文的完整快照
    #     * 轻量记忆  —— 自动的、固定路径的、只含"人填的部分"（细纲/模板/前后缀）
    #   启动时自动恢复，所以用户不用再点一次「选文件 / 开始分章」。

    def _save_last_project(self) -> bool:
        """把当前工程的「人填部分」存成轻量记忆（几 KB，可频繁调用）。"""
        proj = getattr(self, "_project", None)
        if proj is None:
            return False
        try:
            from src import config as C

            self._collect_notes()      # 先把界面上的细纲/模板同步进工程
            ok = bool(proj.save_sidecar(C.LAST_PROJECT))
            if ok and hasattr(self, "_refresh_run_todo"):
                self._refresh_run_todo()
            return ok
        except Exception as e:
            print(f"[ui] 保存轻量记忆失败：{e}")
            return False

    def _restore_last_project(self) -> bool:
        """启动时恢复「上次载入的小说」（含手填细纲 / 模板 / 前后缀）。

        ★ 同步执行即可：实测用户那本 0.16MB / 100 章**重新分章只要 5ms**
          （sidecar 里不存正文，只存路径 + 细纲，所以永远和 txt 一致）。
        """
        if getattr(self, "_project", None) is not None:
            return True                # 已经载入过了，别覆盖
        try:
            from src import config as C
            from src.novel import NovelProject

            proj = NovelProject.restore_sidecar(C.LAST_PROJECT)
        except Exception as e:
            print(f"[ui] 恢复上次的小说失败：{e}")
            return False
        if proj is None:
            return False

        self._project = proj
        n = len(proj.chapters)
        notes = sum(1 for c in proj.chapters if c.note.strip())
        # 让界面与工程一致：先画出章节列表，再用界面上的模板/前后缀覆盖工程字段
        try:
            self._render_chapters()
        except Exception:
            pass
        try:
            self._collect_notes()
        except Exception:
            pass
        if hasattr(self, "_split_hint"):
            self._split_hint.config(
                text=f"✓ 已自动恢复上次的小说：《{proj.name}》共 {n} 章"
                     + (f"，其中 {notes} 章有手填细纲" if notes else "")
                     + "（无需重新分章）")
        self.log(f"✓ 已自动恢复上次载入的小说：《{proj.name}》{n} 章"
                 + (f"（含 {notes} 章手填细纲）" if notes else "")
                 + "，不用再点「开始分章」", "ok")
        if hasattr(self, "_refresh_run_todo"):
            try:
                self._refresh_run_todo()
            except Exception:
                pass
        return True

    def _collect_notes(self):
        """把界面上输入框的内容回写到 project。"""
        if self._project is None:
            return
        for c in self._project.chapters:
            e = self._ch_entries.get(c.no)
            if e is not None:
                c.note = e.get().strip()
        # ★ 指令模板
        if hasattr(self, "_tpl_text"):
            self._project.instruction = self._get_instruction()
        # ★ 统一前后缀：只有勾选了才生效，否则清空
        if self._use_wrap.get():
            self._project.global_prefix = self._prefix_entry.get().strip()
            self._project.global_suffix = self._suffix_entry.get().strip()
        else:
            self._project.global_prefix = ""
            self._project.global_suffix = ""

    def _save_project(self):
        from tkinter import filedialog

        if self._project is None:
            self.log("还没有分章，先选文件分章", "warn")
            return
        self._collect_notes()
        p = filedialog.asksaveasfilename(
            title="保存小说工程",
            defaultextension=".json",
            initialfile=f"{self._project.name}.novel.json",
            filetypes=[("小说工程", "*.json"), ("所有文件", "*.*")],
        )
        if not p:
            return
        try:
            self._project.save(p)
            self.log(f"工程已保存：{p}", "ok")
            self.status.set_status("已保存", "ok")
        except Exception as e:
            self.log(f"保存失败：{e}", "err")

    def _open_project(self):
        from tkinter import filedialog

        p = filedialog.askopenfilename(
            title="打开小说工程",
            filetypes=[("小说工程", "*.json"), ("所有文件", "*.*")],
        )
        if not p:
            return
        try:
            from src.novel import NovelProject

            proj = NovelProject.open(p)
            self._project = proj
            if proj.source:
                self._novel_entry.set(proj.source)
            self._prefix_entry.set(proj.global_prefix)
            self._suffix_entry.set(proj.global_suffix)
            # ★ 载入指令模板（并同步勾选状态）
            self._set_tpl(proj.instruction or "#1")
            if proj.global_prefix or proj.global_suffix:
                self._use_wrap.set(True)
                self._toggle_wrap()
            self._render_chapters()
            self._split_hint.config(
                text=f"✓ 已载入工程《{proj.name}》 {len(proj.chapters)} 章")
            self.log(f"已载入工程：{p}", "ok")
        except Exception as e:
            self.log(f"载入失败：{e}", "err")


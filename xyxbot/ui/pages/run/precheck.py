"""开跑前预检（本地瞬时预检 + 上站点深度核对）。

本文件由 `xyxbot/ui/pages/run.py` 拆分而来（class split），
只搬位置、不改逻辑：方法体、注释、超时值全部原样。
"""

from __future__ import annotations

from xyxbot.runplan import (Check, Progress, format_checks,
                         has_blocking_error, preflight)
from xyxbot.ui.theme import (COLOR, F, BrandButton, Card, CheckBox, Collapsible,
                     DarkEntry, DimLabel, TitleLabel, bind_configure,
                     bind_wheel)
import tkinter as tk


class RunPrecheckMixin:
    """开跑前预检（本地瞬时预检 + 上站点深度核对）。"""

    # ============================================================ 预检

    def _run_local_checks(self) -> list:
        """本地预检（瞬时，不开浏览器）。"""
        book = ""
        try:
            book = self._ai_book_entry.get().strip()
        except Exception:
            pass
        start = self._run_read_int(self._batch_start_entry, 0)
        end = self._run_read_int(self._batch_end_entry, 0)

        try:
            st = self._prepare_state() or {}
            logged = bool(st.get("saved"))
            age = st.get("age") or ""
        except Exception:
            logged, age = False, ""

        # 模板 / 细纲状态
        tpl, unknown, empty, preview_len = "", [], [], 0
        proj = getattr(self, "_project", None)
        try:
            self._collect_notes()
            proj = getattr(self, "_project", None)
            if proj is not None:
                proj.instruction = self._get_instruction()
                tpl = proj.instruction or ""
        except Exception:
            tpl = ""
        if proj is not None and tpl:
            try:
                chk = proj.check_template(tpl)
                unknown = list(chk.get("unknown") or [])
                empty = list(chk.get("empty") or [])
            except Exception:
                pass
            try:
                rendered = proj.render_for_batch(
                    self._resolve_current_chapter_no() or 1, template=tpl)
                preview_len = len(rendered or "")
            except Exception:
                preview_len = 0

        return preflight(
            book=book, start=start, end=end,
            site_chapters=self._run_site_chapters,
            auto_new=bool(self._batch_autonew_var.get()),
            template=tpl, unknown_codes=unknown, empty_codes=empty,
            logged_in=logged, session_age=age,
            has_project=proj is not None,
            project_name=(proj.name if proj is not None else ""),
            project_chapters=(len(proj.chapters) if proj is not None else 0),
            preview_len=preview_len)

    def _run_show_checks(self, checks: list) -> None:
        for w in self._run_checks_box.winfo_children():
            w.destroy()
        self._run_last_checks = list(checks)
        DimLabel(self._run_checks_box, "预检结果", size=9).pack(anchor="w")
        colors = {"ok": COLOR["success"], "warn": COLOR["warning"],
                  "err": COLOR["danger"]}
        for c in checks:
            line = tk.Frame(self._run_checks_box, bg=COLOR["bg_card"])
            line.pack(fill="x", pady=1)
            tk.Label(line, text=c.icon(), font=F(9, True),
                     bg=COLOR["bg_card"],
                     fg=colors.get(c.level, COLOR["text_dim"])).pack(side="left")
            tk.Label(line, text=" " + c.title, font=F(9), bg=COLOR["bg_card"],
                     fg=COLOR["text"]).pack(side="left")
            if c.detail:
                tk.Label(line, text="  " + c.detail, font=F(8),
                         bg=COLOR["bg_card"],
                         fg=COLOR["text_mute"]).pack(side="left")
        for ln in format_checks(checks):
            self.log("预检 " + ln, "info")

    def _run_precheck(self, deep: bool = False) -> list:
        """跑预检；`deep=True` 时另外起一个后台任务去站点上核对作品与章节。"""
        checks = self._run_local_checks()
        self._run_show_checks(checks)
        if deep:
            self._run_precheck_deep_async()
        return checks

    def _run_precheck_deep(self):
        self._run_precheck(deep=True)

    def _run_precheck_deep_async(self):
        """后台：打开作品 → 读站点章节号 → 再补一轮预检。"""
        book = ""
        try:
            book = self._ai_book_entry.get().strip()
        except Exception:
            pass
        if not book:
            self.log("预检：没填作品名，跳过站点核对", "warn")
            return
        _idx, ok = self._parse_book_index()
        if not ok:
            return

        def worker():
            from xyxbot import books as B
            from xyxbot import ai as AI
            try:
                page = self._ensure_page()
            except Exception as e:
                self.after(0, self.log, f"预检：浏览器起不来（{e}）", "err")
                return
            try:
                self.after(0, self.log, f"预检：正在核对作品《{book}》…", "brand")
                if not B.open_book(page, book, console_pick=False,
                                   index=self._ai_book_index, wait=3.0):
                    self.after(0, self._run_precheck_deep_done, None,
                               "打不开这个作品 —— 确认名字对不对")
                    return
                nos = AI.chapter_numbers(page)
                self.after(0, self._run_precheck_deep_done, nos, "")
            except Exception as e:
                self.after(0, self._run_precheck_deep_done, None, str(e))

        self._run_guarded("跑章预检", worker)

    def _run_precheck_deep_done(self, nos, err: str = ""):
        if err:
            self.log(f"预检：站点核对失败 —— {err}", "warn")
            self._run_show_checks(self._run_local_checks()
                                  + [Check("err", "站点核对失败", err)])
            self._refresh_run_status()
            return
        if nos is None:
            self._run_show_checks(self._run_local_checks()
                                  + [Check("err", "作品打不开")])
            self._refresh_run_status()
            return
        self._run_site_chapters = list(nos)
        self.log(f"预检：站点上《{self._ai_book_entry.get().strip()}》"
                 f"共 {len(nos)} 章"
                 + (f"（{min(nos)}~{max(nos)}）" if nos else ""), "ok")
        self._refresh_run_range_hint()
        self._refresh_run_status()
        self._run_show_checks(self._run_local_checks())

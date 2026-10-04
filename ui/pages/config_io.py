"""工作区配置持久化（workspace.json 的记住与回填）。

从 ui/main_window.py 拆出的独立模块（架构改良阶段二）。

这些方法都是「界面控件 ↔ workspace.json」的编解码，与页面渲染无关，
放在这里让窗口类不必再背着 25 个字段的搬运逻辑。

★ 依赖（由 MRO 解析，见 content.py 的说明）：
     调用了 chapters 模块的 _do_split / _set_tpl / _toggle_wrap /
     _get_instruction。
"""

from __future__ import annotations

from pathlib import Path

from ..defaults import (
    DEFAULT_AUTO_ACCEPT,
    DEFAULT_REVIEW_REPLACE,
    DEFAULT_REVIEW_SELECT_ALL,
    DEFAULT_REVIEW_WAIT,
)
from ..theme import COLOR, BrandButton


class ConfigIOMixin:
    """工作区配置的读取/回填/保存。"""

    def _restore_ws(self):
        """启动 / 切到本页时，把上次保存的配置回填到界面。

        ★ 2026-10-04：新增「跑章范围 / 缺章自动新建 / 失败就停」的回填 ——
          以前这几项**完全没存**，每次跑章都要重新手输起止章号。
        ★ 同时给控件加了 `hasattr` 守卫：小说文件输入框现在在「跑章」页，
          而本方法可能被别的页调用（页面是构建一次常驻的，正常都在，
          但缺了也不该抛异常）。
        """
        try:
            from src.workspace import load_ws
            ws = load_ws()
        except Exception:
            return

        # 小说路径（文件还在才回填）
        p = ws.get("novel_path") or ""
        if hasattr(self, "_novel_entry"):
            if p and Path(p).exists():
                self._novel_entry.set(p)
                if hasattr(self, "_split_hint"):
                    self._split_hint.config(
                        text=f"✓ 已载入上次的配置：{Path(p).name}"
                             f"（可直接点「开始分章」）")
            elif p and hasattr(self, "_split_hint"):
                self._split_hint.config(text=f"上次的文件已不在：{p}")

        # 作品名 / 序号 / 快捷选项
        if ws.get("book_name"):
            self._ai_book_entry.set(str(ws["book_name"]))
        if ws.get("book_index"):
            self._ai_idx_entry.set(str(ws["book_index"]))
        if ws.get("shortcut"):
            self._ai_shortcut_entry.set(str(ws["shortcut"]))

        # ★ 自动采纳参数
        try:
            self._ai_auto_var.set(bool(ws.get("auto_accept",
                                              DEFAULT_AUTO_ACCEPT)))
        except Exception:
            pass
        if ws.get("min_words"):
            self._ai_min_entry.set(str(ws["min_words"]))
        if ws.get("max_words"):
            self._ai_max_entry.set(str(ws["max_words"]))
        if ws.get("max_retry"):
            self._ai_retry_entry.set(str(ws["max_retry"]))

        # ★ AI 审稿参数
        if ws.get("review_model"):
            self._rv_model_entry.set(str(ws["review_model"]))
        if ws.get("review_card"):
            self._rv_card_entry.set(str(ws["review_card"]))
        if ws.get("review_associate"):
            self._rv_assoc_entry.set(str(ws["review_associate"]))
        if ws.get("review_req"):
            self._rv_req_entry.set(str(ws["review_req"]))
        # ★ 审稿流程开关
        try:
            self._rv_wait_var.set(bool(ws.get("review_wait",
                                              DEFAULT_REVIEW_WAIT)))
        except Exception:
            pass
        try:
            self._rv_replace_var.set(bool(ws.get("review_replace",
                                                 DEFAULT_REVIEW_REPLACE)))
        except Exception:
            pass
        if ws.get("review_timeout"):
            self._rv_timeout_entry.set(str(ws["review_timeout"]))
        # ★ 追加指令 / 先打开章节 / 替换前全选
        if ws.get("review_instruction"):
            self._rv_instr_text.delete("1.0", "end")
            self._rv_instr_text.insert("1.0", str(ws["review_instruction"]))
        if ws.get("review_chapter"):
            self._rv_chapter_entry.set(str(ws["review_chapter"]))
        try:
            self._rv_select_all_var.set(
                bool(ws.get("review_select_all", DEFAULT_REVIEW_SELECT_ALL)))
        except Exception:
            pass

        # 指令模板
        if ws.get("instruction") and hasattr(self, "_set_tpl"):
            self._set_tpl(str(ws["instruction"]))

        # ★★ 跑章范围与开关（2026-10-04 新增持久化）
        if ws.get("batch_start") and hasattr(self, "_batch_start_entry"):
            self._batch_start_entry.set(str(ws["batch_start"]))
        if ws.get("batch_end") and hasattr(self, "_batch_end_entry"):
            self._batch_end_entry.set(str(ws["batch_end"]))
        if hasattr(self, "_batch_autonew_var"):
            try:
                self._batch_autonew_var.set(bool(ws.get("batch_auto_new", True)))
            except Exception:
                pass
        if hasattr(self, "_batch_stop_on_fail_var"):
            try:
                self._batch_stop_on_fail_var.set(
                    bool(ws.get("batch_stop_on_fail", False)))
            except Exception:
                pass

        # 前后缀
        if hasattr(self, "_use_wrap"):
            self._use_wrap.set(bool(ws.get("use_wrap")))
            self._prefix_entry.set(str(ws.get("prefix") or ""))
            self._suffix_entry.set(str(ws.get("suffix") or ""))
            if hasattr(self, "_toggle_wrap"):
                self._toggle_wrap()

        # ★★ 界面/环境类的记忆（2026-10-04）
        #   浏览器内核路径：原来只存在内存字段里，重启又走一遍自动检测
        if ws.get("browser_path"):
            self._browser_path_value = str(ws["browser_path"])
            if hasattr(self, "_browser_entry"):
                try:
                    self._browser_entry.set(self._browser_path_value)
                except Exception:
                    pass
        #   日志「只看关键节点」
        if hasattr(self, "_log_keyonly"):
            try:
                on = bool(ws.get("log_key_only", False))
                self._log_keyonly.set(on)
                self.log_view.set_key_only(on)
            except Exception:
                pass
        #   单章工具「续写后自动关弹窗」
        if hasattr(self, "_auto_both_close_var"):
            try:
                self._auto_both_close_var.set(
                    bool(ws.get("auto_both_close", True)))
            except Exception:
                pass

        # 最近文件按钮
        self._render_history()

        # ★★ 自动恢复「上次载入的小说」（含手填细纲）—— 这样启动就绪，
        #    用户不用再点一次「选文件 / 开始分章」。
        if hasattr(self, "_restore_last_project"):
            try:
                self._restore_last_project()
            except Exception:
                pass

        # 跑章页的状态条/范围提示依赖这些值
        if hasattr(self, "_refresh_run_status"):
            try:
                self._refresh_run_status()
                self._refresh_run_range_hint()
                self._refresh_run_last()
                self._refresh_run_todo()
            except Exception:
                pass

    def _render_history(self):
        """渲染「最近文件」快捷按钮。"""
        if not hasattr(self, "_hist_box"):
            return
        for w in self._hist_box.winfo_children():
            w.destroy()
        try:
            from src.workspace import load_ws
            hist = load_ws().get("history", [])
        except Exception:
            hist = []
        hist = [h for h in hist if Path(h).exists()]
        if not hist:
            self._hist_lbl.config(text="")
            return
        self._hist_lbl.config(text="最近：")
        for h in hist[:4]:
            name = Path(h).stem
            if len(name) > 14:
                name = name[:14] + "…"
            BrandButton(self._hist_box, name, width=150, height=26,
                        style="ghost", bg=COLOR["bg_card"], font_size=8,
                        command=lambda p=h: self._use_history(p)).pack(
                side="left", padx=(4, 0))

    def _use_history(self, path: str):
        """点最近文件：填入并直接分章。"""
        self._novel_entry.set(path)
        self.log(f"使用最近文件：{Path(path).name}", "brand")
        self._do_split()

    def _collect_ws(self) -> dict:
        """把界面上的配置项收集成 dict。"""
        return {
            "novel_path": self._novel_entry.get().strip().strip('"'),
            "book_name": self._ai_book_entry.get().strip(),
            "book_index": self._ai_idx_entry.get().strip(),
            "shortcut": self._ai_shortcut_entry.get().strip(),
            "instruction": self._get_instruction(),
            "use_wrap": bool(self._use_wrap.get()),
            "prefix": self._prefix_entry.get().strip(),
            "suffix": self._suffix_entry.get().strip(),
            # ★ 自动采纳参数
            "auto_accept": bool(self._ai_auto_var.get()),
            "min_words": self._ai_min_entry.get().strip(),
            "max_words": self._ai_max_entry.get().strip(),
            "max_retry": self._ai_retry_entry.get().strip(),
            # ★ AI 审稿参数
            "review_model": self._rv_model_entry.get().strip(),
            "review_card": self._rv_card_entry.get().strip(),
            "review_associate": self._rv_assoc_entry.get().strip(),
            "review_req": self._rv_req_entry.get().strip(),
            "review_wait": bool(self._rv_wait_var.get()),
            "review_replace": bool(self._rv_replace_var.get()),
            "review_timeout": self._rv_timeout_entry.get().strip(),
            # ★ 追加指令 / 先打开章节 / 替换前全选（2026-10-03）
            "review_instruction": self._rv_instr_text.get(
                "1.0", "end").strip(),
            "review_chapter": self._rv_chapter_entry.get().strip(),
            "review_select_all": bool(self._rv_select_all_var.get()),
            # ★★ 跑章范围与开关（2026-10-04 新增持久化）
            "batch_start": self._batch_start_entry.get().strip(),
            "batch_end": self._batch_end_entry.get().strip(),
            "batch_auto_new": bool(self._batch_autonew_var.get()),
            "batch_stop_on_fail": bool(self._batch_stop_on_fail_var.get()),
            # ★★ 界面/环境类（2026-10-04）
            "browser_path": (self._browser_path_override() or ""),
            "log_key_only": bool(getattr(self, "_log_keyonly", None)
                                 and self.log_view.key_only()),
            "auto_both_close": bool(
                getattr(self, "_auto_both_close_var", None)
                and self._auto_both_close_var.get()),
        }

    def _save_ws(self, silent: bool = False):
        """保存当前界面配置（分章成功、点一键续写时自动调用）。"""
        try:
            from src.workspace import save_from_ui
            d = self._collect_ws()
            save_from_ui(**d)
            # ★ 顺带把「上次载入的小说」（细纲/模板）也存一份轻量记忆，
            #   这样即使用户没点「另存工程」，下次启动也不会丢细纲。
            if hasattr(self, "_save_last_project"):
                try:
                    self._save_last_project()
                except Exception:
                    pass
            if not silent:
                self.log(f"✓ 已保存配置（下次自动回填）", "ok")
                self.status.set_status("配置已保存", "ok")
            self._render_history()
            return True
        except Exception as e:
            if not silent:
                self.log(f"保存配置失败：{e}", "err")
            return False

    def _save_ws_click(self):
        self._save_ws(silent=False)

"""开始 / 停止 / 清空结果。

本文件由 `xyxbot/ui/pages/run.py` 拆分而来（class split），
只搬位置、不改逻辑：方法体、注释、超时值全部原样。
"""

from __future__ import annotations

from xyxbot.runplan import (Check, Progress, format_checks,
                         has_blocking_error, preflight)


class RunControlMixin:
    """开始 / 停止 / 清空结果。"""

    # ============================================================ 开始 / 停止

    def _run_start(self):
        """开始跑章：先预检，有阻塞问题就拒绝开跑。"""
        import threading

        checks = self._run_precheck(deep=False)
        if has_blocking_error(checks):
            bad = [c for c in checks if c.is_error]
            self.log(f"✗ 预检没通过（{len(bad)} 项阻塞），已取消开跑", "err")
            for c in bad:
                self.log(f"    ✗ {c.title} —— {c.detail}", "err")
            self.status.set_status("预检未通过", "err")
            return
        warns = [c for c in checks if c.level == "warn"]
        for c in warns:
            self.log(f"⚠ {c.title} —— {c.detail}", "warn")

        # 重置进度
        self._run_clear_results()
        self._run_progress = Progress()
        self._run_draw_progress()

        if hasattr(self, "_run_col_params"):
            self._run_col_params.set_open(False)
        if hasattr(self, "_run_col_notes"):
            self._run_col_notes.set_open(False)

        # 交给 ai_flow 的批量实现（它读的是同一批控件）
        self._ai_batch_go()

    def _run_stop(self):
        """请求停止：协作式取消，最长一个轮询周期（≤0.25s）生效。"""
        from xyxbot import ai as AI

        if not AI.cancel_requested():
            AI.request_cancel()
            self.log("⏹ 已请求停止 —— 正在等当前步骤退出（通常几秒内）", "warn")
            self.status.set_status("正在停止…", "warn")
        else:
            self.log("⏹ 停止请求已经发出过了，稍等", "info")

    def _run_set_stop_enabled(self, on: bool):
        """开关「停止」按钮（只有任务真的跑起来了才让它可点）。"""
        btn = getattr(self, "_btn_run_stop", None)
        if btn is None:
            return
        try:
            btn.set_enabled(bool(on))
        except Exception:
            pass

    def _run_clear_results(self):
        for w in self._run_res_list.winfo_children():
            w.destroy()
        self._run_result_rows = 0
        self._run_results_data = []
        try:
            self._run_empty_lbl.pack(anchor="w")
        except Exception:
            pass

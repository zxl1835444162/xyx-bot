"""结果收尾（拉到最新章 / 导出 CSV / 复制失败章号 / 重试失败章）。

本文件由 `xyxbot/ui/pages/run.py` 拆分而来（class split），
只搬位置、不改逻辑：方法体、注释、超时值全部原样。
"""

from __future__ import annotations

from xyxbot.runplan import (Check, Progress, format_checks,
                         has_blocking_error, preflight)


class RunResultMixin:
    """结果收尾（拉到最新章 / 导出 CSV / 复制失败章号 / 重试失败章）。"""

    # ============================================================ 结果处理

    def _run_range_to_latest(self):
        """把「结束章」拉到站点已知的最新章（保留起始章）。"""
        site = self._run_site_chapters
        if not site:
            self.log("还不知道站点上有哪些章 —— 先点「预检（不跑）」查一次",
                     "warn")
            return
        end = max(site)
        start = self._run_read_int(self._batch_start_entry, 0) or 1
        if start > end:
            start = end
        self._batch_start_entry.set(str(start))
        self._batch_end_entry.set(str(end))
        self._refresh_run_range_hint()
        self.log(f"结束章已设为站点最新章：第 {end} 章", "brand")

    def _run_export_results(self):
        """把逐章结果导出成 CSV（UTF-8-BOM，Excel 打开不乱码）。"""
        rows = list(getattr(self, "_run_results_data", []) or [])
        if not rows:
            self.log("还没有结果可导出", "warn")
            return
        try:
            import csv
            from datetime import datetime

            from xyxbot import config as C

            out_dir = C.ARTIFACTS / "exports"
            out_dir.mkdir(parents=True, exist_ok=True)
            p = out_dir / f"跑章结果-{datetime.now():%Y%m%d-%H%M%S}.csv"
            with open(p, "w", encoding="utf-8-sig", newline="") as f:
                w = csv.writer(f)
                w.writerow(["章号", "结果", "字数", "耗时秒", "原因"])
                for r in rows:
                    verdict = ("中止" if r.get("aborted")
                               else ("成功" if r.get("ok") else "失败"))
                    w.writerow([
                        r.get("no", ""), verdict, r.get("words") or "",
                        f"{float(r.get('elapsed') or 0):.1f}",
                        r.get("reason") or "",
                    ])
            self.log(f"✓ 结果已导出（{len(rows)} 行）：{p}", "ok")
            self.status.set_status("结果已导出", "ok")
        except Exception as e:
            self.log(f"导出失败：{e}", "err")

    def _run_copy_failed(self):
        """把失败章号复制到剪贴板（形如 ``5,7,9``）。"""
        p = getattr(self, "_run_progress", None)
        failed = list(getattr(p, "failed", []) or [])
        if not failed:
            self.log("没有失败章，不用复制", "info")
            return
        txt = ",".join(str(x) for x in failed)
        try:
            self.clipboard_clear()
            self.clipboard_append(txt)
        except Exception as e:
            self.log(f"写剪贴板失败（{e}），失败章号：{txt}", "warn")
            return
        self.log(f"已复制失败章号到剪贴板：{txt}", "ok")
        self.status.set_status(f"已复制 {len(failed)} 个失败章号", "ok")

    def _run_retry_failed(self):
        from xyxbot.runplan import next_retry_range

        p = getattr(self, "_run_progress", Progress())
        end = self._run_read_int(self._batch_end_entry, 0)
        rng = next_retry_range(p, end)
        if not rng:
            self.log("没有失败章，不用重跑", "info")
            return
        start, end2 = rng
        self._batch_start_entry.set(str(start))
        self._batch_end_entry.set(str(end2))
        self._refresh_run_range_hint()
        skipped = [x for x in range(start, end2 + 1) if x not in p.failed]
        self.log(f"已把范围改成 第{start}~{end2} 章（{len(p.failed)} 个失败章）"
                 + (f"；注意第 {'、'.join(map(str, skipped))} 章会重跑一遍"
                    if skipped else ""), "brand")
        self.status.set_status(f"已设好重跑范围 {start}~{end2}", "ok")

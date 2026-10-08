"""「跑章」页 —— 本项目唯一的主流程（已按职责拆成多个 Mixin）。

  「跑章」页 —— 本项目**唯一的主流程**（2026-10-04 界面重设计）。
  
  设计目标（用户原话）：
      「我在操作上感觉很分散……我仅仅使用的功能，仅有这个流水化的
        从某章到某章的续写。」
  
  所以这一页把整条流水线按**从上到下**排成一列，一页配完就能开跑：
  
      状态条  →  ① 目标作品  →  ② 跑章范围  →  ③ 每章指令（核心）
              →  ④ 细纲来源(折叠)  →  ⑤ 高级参数(折叠)
              →  ⑥ 预检 / 开始 / 停止
              →  ⑦ 进度 + ETA + 逐章结果
  
  ★ 关于控件命名：页面里所有 `self._ai_*` / `self._rv_*` / `self._batch_*` /
    `self._tpl_*` / `self._ch_*` / `self._novel_*` 都**沿用原来的名字**，
    这样 `config_io.py`（记住/回填）、`chapters.py`（分章/模板/细纲）、
    `ai_flow.py`（跑章编排）**一行都不用改**。
  
  ★ 依赖（由 MRO 解析）：`_page_header` / `log` / `status` / `_run_guarded` /
    `_ensure_page`（窗口）、`_restore_ws` / `_save_ws`（config_io）、
    `_do_split` / `_set_tpl` / `_get_instruction` / `_collect_notes` /
    `_update_tpl_preview` / `_render_chapters` / `_resolve_current_chapter_no` /
    `_parse_book_index`（chapters）、`_ai_batch_go`（ai_flow）。
"""

from __future__ import annotations

from xyxbot.ui.pages.run.page import RunPageMixin
from xyxbot.ui.pages.run.form import RunFormMixin
from xyxbot.ui.pages.run.precheck import RunPrecheckMixin
from xyxbot.ui.pages.run.control import RunControlMixin
from xyxbot.ui.pages.run.progress import RunProgressMixin
from xyxbot.ui.pages.run.result import RunResultMixin

__all__ = ["RunMixin"]


class RunMixin(RunPageMixin, RunFormMixin, RunPrecheckMixin, RunControlMixin, RunProgressMixin, RunResultMixin):
    """「跑章」页的构建 + 进度/预检/停止的界面逻辑。"""

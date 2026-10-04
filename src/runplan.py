"""跑章进度 / 预计剩余 / 开跑前预检 —— **纯逻辑**，不依赖 tkinter 与 playwright。

★★ 为什么要单独一个模块（2026-10-04 界面重设计）
================================================

「跑章」页要显示这些东西：

  * 进度：`██████░░░░  4/8 章   当前：第6章 · 审稿中`
  * 节奏：`已用 8分12秒 · 平均 2分03秒/章 · 预计剩余 约8分钟`
  * 预检：开始前一次性告诉用户"哪里不对"，而不是跑到第 5 章才发现

这些全是**算出来的数**，跟界面无关。放在 `ui/` 里就没法单测（要建窗口），
所以抽到这里：界面只负责把数字画出来。

对应地，测试可以完全不碰浏览器、不建窗口地把逻辑钉死。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Sequence

# ---------------------------------------------------------------- 预检

LEVEL_ERR = "err"      # 必须解决，否则不该开跑
LEVEL_WARN = "warn"    # 能跑，但很可能不如预期
LEVEL_OK = "ok"


@dataclass
class Check:
    """一条预检结果。"""

    level: str
    title: str
    detail: str = ""

    @property
    def is_error(self) -> bool:
        return self.level == LEVEL_ERR

    def icon(self) -> str:
        return {LEVEL_ERR: "✗", LEVEL_WARN: "⚠", LEVEL_OK: "✓"}.get(
            self.level, "·")


def preflight(*,
              book: str = "",
              start: int = 0,
              end: int = 0,
              site_chapters: Optional[Sequence[int]] = None,
              auto_new: bool = True,
              template: str = "",
              unknown_codes: Sequence[int] = (),
              empty_codes: Sequence[int] = (),
              logged_in: bool = False,
              session_age: str = "",
              has_project: bool = False,
              project_name: str = "",
              project_chapters: int = 0,
              preview_len: int = 0) -> List[Check]:
    """开跑前把所有能提前查的都查一遍。

    全部是**只读**检查：不打开浏览器、不发请求。`site_chapters` 由调用方
    （如果已经连上浏览器）传入；传 None 表示"还没连站点，跳过这一条"。

    Returns:
        List[Check]：至少会有一条。界面按 level 上色。
    """
    out: List[Check] = []
    site = list(site_chapters) if site_chapters else []

    # ① 登录态
    if logged_in:
        out.append(Check(LEVEL_OK, "登录态已就绪",
                         f"上次保存：{session_age}" if session_age else ""))
    else:
        out.append(Check(LEVEL_ERR, "尚未保存登录态",
                         "先去「准备」页点「打开网站并保存」，否则开跑就会卡在登录页"))

    # ② 作品名
    if book.strip():
        out.append(Check(LEVEL_OK, f"目标作品《{book.strip()}》"))
    else:
        out.append(Check(LEVEL_ERR, "没填作品名",
                         "填站点上那本书的名字（同名多本再填「第几本」）"))

    # ③ 章节范围
    if start < 1 or end < 1:
        out.append(Check(LEVEL_ERR, "章节范围没填全",
                         "起始章和结束章都要是正整数，例如 3 和 10"))
    elif end < start:
        out.append(Check(LEVEL_ERR, "结束章小于起始章",
                         f"现在是 {start} → {end}"))
    else:
        n = end - start + 1
        out.append(Check(LEVEL_OK, f"跑章范围 第 {start} ~ {end} 章（共 {n} 章）"))

    # ④ 与站点现有章节对照（只在这一条能算的时候算）
    if site and start >= 1 and end >= start:
        have = [c for c in range(start, end + 1) if c in site]
        miss = [c for c in range(start, end + 1) if c not in site]
        if not miss:
            out.append(Check(LEVEL_OK,
                             f"要跑的 {len(have)} 章站点上都已存在"))
        else:
            head = "、".join(f"第{c}章" for c in miss[:6])
            more = f" 等 {len(miss)} 章" if len(miss) > 6 else ""
            if auto_new:
                out.append(Check(LEVEL_WARN,
                                 f"有 {len(miss)} 章站点上还没有，将自动新建",
                                 f"{head}{more}"))
            else:
                out.append(Check(LEVEL_ERR,
                                 f"有 {len(miss)} 章不存在，且没勾「缺章自动新建」",
                                 f"{head}{more} —— 这些章会被直接跳过"))

    # ⑤ 细纲来源
    if not has_project:
        out.append(Check(LEVEL_ERR, "还没有载入本地小说并分章",
                         "每章的 `#@` 细纲来自它；去「准备」页选 txt 并点「开始分章」"))
    else:
        out.append(Check(LEVEL_OK,
                         f"细纲已就绪：《{project_name}》共 {project_chapters} 章"))

    # ⑥ 指令模板
    tpl = (template or "").strip()
    if not tpl:
        out.append(Check(LEVEL_ERR, "指令模板是空的",
                         "每章送给站点的「后续剧情」全靠它"))
    else:
        has_cur = "#@" in tpl or "#当前章" in tpl or "{{当前章}}" in tpl
        if unknown_codes:
            out.append(Check(LEVEL_ERR,
                             "指令里引用了不存在的章节代号",
                             "、".join(f"#{n}" for n in sorted(unknown_codes))
                             + " —— 去掉它们，或把它们分章进去"))
        if empty_codes:
            out.append(Check(LEVEL_WARN,
                             f"有 {len(empty_codes)} 章的细纲是空的",
                             "、".join(f"#{n}" for n in sorted(empty_codes)[:8])
                             + " —— 这些章会用原文兜底，效果可能不理想"))
        if not has_cur and not unknown_codes and not empty_codes:
            if "#" not in tpl:
                out.append(Check(LEVEL_WARN, "指令里没有 #@，每章会送同一段文本",
                                 "想每章不一样就加一个 #@（代表当前章细纲）"))
            else:
                out.append(Check(LEVEL_OK,
                                 "指令里的 #N 会被当作「当前章」处理（每章各自的大纲）"))
        if preview_len > 0:
            out.append(Check(LEVEL_OK,
                             f"当前章渲染出 {preview_len} 字的「后续剧情」"))

    return out


def has_blocking_error(checks: Sequence[Check]) -> bool:
    """预检里是否有「必须解决」的项。"""
    return any(c.is_error for c in checks)


def format_checks(checks: Sequence[Check]) -> List[str]:
    """把预检结果压成一行行文字（给日志面板用）。"""
    lines = []
    for c in checks:
        line = f"{c.icon()} {c.title}"
        if c.detail:
            line += f" —— {c.detail}"
        lines.append(line)
    return lines


# ---------------------------------------------------------------- 进度 / ETA

# 还没有完成任何一章时，ETA 用这个经验值先估一个（秒/章）。
# 依据：用户日志里单章 ≈ 生成 9~63s + 审稿 29s + UI ~5s ≈ 45~100s，
# 加上切章/重试的余量，取 120 秒作为"保守的初值"。
DEFAULT_SECONDS_PER_CHAPTER = 120.0


def fmt_duration(seconds: float) -> str:
    """把秒格式化成「1小时2分」/「3分12秒」/「45秒」。"""
    try:
        s = int(max(0, round(seconds)))
    except Exception:
        return "—"
    if s < 60:
        return f"{s}秒"
    m, sec = divmod(s, 60)
    if m < 60:
        return f"{m}分{sec}秒" if sec else f"{m}分"
    h, m = divmod(m, 60)
    return f"{h}小时{m}分" if m else f"{h}小时"


@dataclass
class Progress:
    """跑章进度（界面只读它，不自己算）。"""

    total: int = 0
    done: int = 0                       # 已结束（含失败）的章数
    ok_count: int = 0
    failed: List[int] = field(default_factory=list)
    aborted: List[int] = field(default_factory=list)
    running_no: int = 0                 # 当前正在跑的章号（0=没在跑）
    phase: str = ""                     # "start" | "done" | ""
    elapsed: float = 0.0                # 本次跑章已用秒数
    # 已完成各章的耗时（按完成顺序），用于算真实均值
    chapter_seconds: List[float] = field(default_factory=list)

    # ---- 派生值 ----

    @property
    def percent(self) -> float:
        """0~100。没有 total 时返回 0。"""
        if self.total <= 0:
            return 0.0
        return max(0.0, min(100.0, 100.0 * self.done / self.total))

    @property
    def remaining(self) -> int:
        return max(0, self.total - self.done)

    @property
    def avg_seconds(self) -> float:
        """每章平均耗时（用**真实的**已完成章耗时；没有就用经验值）。"""
        vals = [x for x in self.chapter_seconds if x > 0]
        if not vals:
            return DEFAULT_SECONDS_PER_CHAPTER
        return sum(vals) / len(vals)

    @property
    def eta_seconds(self) -> float:
        """预计剩余秒数。

        ★ 正在跑的那一章按**半章**计入剩余（它已经跑了一半左右），
          比整章计入更贴近实际，也不会在最后一章时显示成 0。
        """
        if self.total <= 0:
            return 0.0
        avg = self.avg_seconds
        if self.done >= self.total:
            return 0.0
        rem = self.total - self.done
        if self.phase == "start" and self.running_no:
            return avg * (rem - 1) + avg * 0.5
        return avg * rem

    @property
    def is_finished(self) -> bool:
        return self.total > 0 and self.done >= self.total

    def apply(self, ev: dict) -> None:
        """吃一个 `ai_batch_chapters(on_progress=...)` 事件。"""
        if not isinstance(ev, dict):
            return
        if ev.get("total"):
            self.total = int(ev["total"])
        if ev.get("total_elapsed") is not None:
            self.elapsed = float(ev.get("total_elapsed") or 0.0)
        phase = ev.get("phase") or ""
        self.phase = phase
        if phase == "start":
            self.running_no = int(ev.get("no") or 0)
            # 已完成的章数由事件里的 done_count 校正（重启/跳章也准）
            if ev.get("done_count") is not None:
                self.done = int(ev["done_count"])
            if ev.get("ok_count") is not None:
                self.ok_count = int(ev["ok_count"])
            return
        if phase == "done":
            no = int(ev.get("no") or 0)
            self.running_no = 0
            if ev.get("done_count") is not None:
                self.done = int(ev["done_count"])
            else:
                self.done += 1
            if ev.get("ok_count") is not None:
                self.ok_count = int(ev["ok_count"])
            secs = float(ev.get("elapsed") or 0.0)
            if secs > 0:
                self.chapter_seconds.append(secs)
            if ev.get("aborted"):
                if no and no not in self.aborted:
                    self.aborted.append(no)
            elif not ev.get("ok"):
                if no and no not in self.failed:
                    self.failed.append(no)

    # ---- 给界面用的一行字 ----

    def line(self) -> str:
        if self.total <= 0:
            return "尚未开始"
        bits = [f"{self.done}/{self.total} 章"]
        if self.running_no and self.phase == "start":
            bits.append(f"当前：第 {self.running_no} 章")
        elif self.is_finished:
            bits.append("已结束")
        if self.failed:
            bits.append("失败 " + ",".join(str(x) for x in self.failed))
        if self.aborted:
            bits.append("已中止")
        return " · ".join(bits)

    def timing_line(self) -> str:
        if self.total <= 0:
            return ""
        if self.is_finished:
            return (f"已用 {fmt_duration(self.elapsed)} · "
                    f"平均 {fmt_duration(self.avg_seconds)}/章")
        return (f"已用 {fmt_duration(self.elapsed)} · "
                f"平均 {fmt_duration(self.avg_seconds)}/章 · "
                f"预计剩余 约{fmt_duration(self.eta_seconds)}")


def next_retry_range(progress: Progress,
                     end: int) -> Optional[tuple]:
    """「从失败章重跑」：给出 (起始, 结束)。

    取**最小的失败章**当起点，保留原有结束章 —— 这样中间已成功的章会被
    重跑一遍（重复生成有成本），所以界面要明确提示；但比"逐章手动跑"省事。
    没有失败章时返回 None。
    """
    if not progress.failed:
        return None
    start = min(progress.failed)
    if end < start:
        return None
    return (start, end)

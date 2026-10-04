"""工作区配置：记住上次用的小说文件 / 作品名 / 指令模板等，免去每次重选。

存到 `artifacts/storage/workspace.json`，跟登录态、凭据放一起。

为什么需要：
    界面「小说分章」页每次打开都要重新选 txt、重填作品名、重写指令模板，
    很烦。这里把「上次用过的」全部记下来，启动时自动回填。

用法：
    from src.workspace import load_ws, save_ws

    ws = load_ws()                       # dict
    ws["novel_path"]                     # 上次的小说 txt
    ws["book_name"]                      # 上次的作品名
    ws["instruction"]                    # 上次的指令模板
    ws["book_index"]                     # 同名多本时的序号
    ws["history"]                        # 最近用过的文件列表（去重，最多 10 个）

    save_ws(novel_path=..., book_name=...)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from src import config as C

WS_FILE = C.STORAGE / "workspace.json"

# 默认值
DEFAULTS: Dict[str, Any] = {
    "novel_path": "",          # 上次选的小说 txt 绝对路径
    "book_name": "",           # 上次填的作品名（站点上那本书）
    "book_index": "",          # 同名多本时的序号（字符串，空=不限）
    "shortcut": "",            # ★ 快捷选项（提示词）关键词
    "instruction": "#1",       # 上次的指令模板
    "use_wrap": False,         # 是否勾了「统一前后缀」
    "prefix": "",              # 统一前缀
    "suffix": "",              # 统一后缀
    # ★ 按字数自动采纳
    "auto_accept": False,      # 是否开启自动采纳
    "min_words": "2100",       # 字数下限（字符串，空=用默认）
    "max_words": "2300",       # 字数上限
    "max_retry": "5",          # 最多重新生成几次
    # ★ AI 审稿
    "review_model": "智慧版",                 # 模型分类
    "review_card": "智慧版-6A",               # 具体模型卡片名
    "review_associate": "正常",               # 联想能力（0.7）
    "review_req": "强盛集团云霄拯救过稿计划",  # 审稿要求关键词
    "review_wait": True,                      # 等生成完成
    "review_replace": True,                   # 完成后点「替换 / 插入」落盘
    "review_timeout": "600",                  # 等生成最长时间（秒）
    "review_instruction": "",                 # ★ 追加指令（与章节正文拼接）
    "review_chapter": "",                     # ★ 先打开的章节（标题关键词）
    "review_select_all": True,                # ★ 替换前先全选正文
    # ★★ 批量跑章的范围与开关（2026-10-04 新增）
    #    之前**完全没持久化** → 每次跑章都要重新手输起止章号（用户实测痛点）
    "batch_start": "",         # 起始章（字符串，空=界面用 placeholder 默认值）
    "batch_end": "",           # 结束章
    "batch_auto_new": True,    # 缺章自动新建
    "batch_stop_on_fail": False,   # 某章失败就停
    # ★★ 「上次跑到哪」（2026-10-04）：跑完/停止后记下来，
    #    界面上给一个「接着上次继续」按钮 —— 连载场景（今天 3~10、
    #    明天 11~20）就不用每次重新算章号了。
    "batch_last_done": "",     # 上次**成功跑完的最高章号**
    "batch_last_span": "",     # 上次跑了多少章（用于推断"下一批同样多章"）
    "batch_last_at": "",       # 上次结束时间（人话）
    # ★★ 界面/环境类的记忆（2026-10-04 用户需求："上次填的，下次不用重填"）
    "browser_path": "",        # 手选/检测到的浏览器内核路径（空=每次自动检测）
    "log_key_only": False,     # 日志面板「只看关键节点」的勾选状态
    "auto_both_close": True,   # 单章工具「续写后自动关弹窗」
    "win_geometry": "",        # 窗口大小+位置，如 1180x980+320+140
    "history": [],             # 最近用过的 txt 路径（最新在前，最多 10）
}

HISTORY_MAX = 10


def load_ws() -> Dict[str, Any]:
    """读配置；文件不存在或损坏时返回默认值（不抛异常）。"""
    data = dict(DEFAULTS)
    data["history"] = []
    if not WS_FILE.exists():
        return data
    try:
        raw = json.loads(WS_FILE.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            for k, v in raw.items():
                data[k] = v
        # 类型兜底
        if not isinstance(data.get("history"), list):
            data["history"] = []
        data["history"] = [str(x) for x in data["history"] if x][:HISTORY_MAX]
    except Exception:
        pass
    return data


def save_ws(**kwargs) -> Dict[str, Any]:
    """合并写入配置。

    只更新传入的键；`history` 特殊处理 —— 传 novel_path 时自动把它挪到最前。
    """
    data = load_ws()

    novel_path = kwargs.pop("novel_path", None)
    if novel_path is not None:
        data["novel_path"] = novel_path
        # 维护历史列表
        h: List[str] = [x for x in data.get("history", []) if x != novel_path]
        h.insert(0, novel_path)
        data["history"] = h[:HISTORY_MAX]

    for k, v in kwargs.items():
        if k in DEFAULTS or k in ("prefix", "suffix"):
            data[k] = v

    try:
        WS_FILE.parent.mkdir(parents=True, exist_ok=True)
        WS_FILE.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8")
    except Exception as e:
        print(f"[workspace] 保存配置失败：{e}")
    return data


def save_from_ui(novel_path: str = "", book_name: str = "",
                 book_index: str = "", shortcut: str = "",
                 instruction: str = "",
                 use_wrap: bool = False, prefix: str = "",
                 suffix: str = "",
                 auto_accept: bool = False, min_words: str = "2100",
                 max_words: str = "2300", max_retry: str = "5",
                 review_model: str = "智慧版",
                 review_card: str = "智慧版-6A",
                 review_associate: str = "正常",
                 review_req: str = "强盛集团云霄拯救过稿计划",
                 review_wait: bool = True,
                 review_replace: bool = True,
                 review_timeout: str = "600",
                 review_instruction: str = "",
                 review_chapter: str = "",
                 review_select_all: bool = True,
                 batch_start: str = "",
                 batch_end: str = "",
                 batch_auto_new: bool = True,
                 batch_stop_on_fail: bool = False,
                 browser_path: str = "",
                 log_key_only: bool = False,
                 auto_both_close: bool = True,
                 ) -> Dict[str, Any]:
    """界面专用：把所有字段一次性存下来（空串也存，代表用户清空了）。"""
    kw: Dict[str, Any] = {
        "book_name": book_name,
        "book_index": book_index,
        "shortcut": shortcut,
        "instruction": instruction,
        "use_wrap": bool(use_wrap),
        "prefix": prefix,
        "suffix": suffix,
        "auto_accept": bool(auto_accept),
        "min_words": min_words,
        "max_words": max_words,
        "max_retry": max_retry,
        "review_model": review_model,
        "review_card": review_card,
        "review_associate": review_associate,
        "review_req": review_req,
        "review_wait": bool(review_wait),
        "review_replace": bool(review_replace),
        "review_timeout": review_timeout,
        "review_instruction": review_instruction,
        "review_chapter": review_chapter,
        "review_select_all": bool(review_select_all),
        "batch_start": batch_start,
        "batch_end": batch_end,
        "batch_auto_new": bool(batch_auto_new),
        "batch_stop_on_fail": bool(batch_stop_on_fail),
        # ★ 界面/环境类
        "browser_path": browser_path,
        "log_key_only": bool(log_key_only),
        "auto_both_close": bool(auto_both_close),
    }
    if novel_path:
        kw["novel_path"] = novel_path
    return save_ws(**kw)


def clear_ws() -> None:
    """清空配置。"""
    try:
        if WS_FILE.exists():
            WS_FILE.unlink()
    except Exception:
        pass


# ---------------------------------------------------------------- 上次进度

def note_batch_run(last_done: int, span: int) -> Dict[str, Any]:
    """记下「这次跑到哪」，供界面上的「接着上次继续」使用。

    Args:
        last_done: 本次**成功跑完的最高章号**（0 表示一章都没成功）
        span:      本次覆盖了多少章（用来推断下一批要不要同样多）
    """
    from datetime import datetime

    return save_ws(
        batch_last_done=str(int(last_done)),
        batch_last_span=str(int(span)),
        batch_last_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
    )


def last_run() -> Dict[str, Any]:
    """读「上次跑到哪」。

    Returns:
        ``{"done": int, "span": int, "at": str, "ok": bool}``
        `ok=False` 表示从来没记录过（界面据此隐藏「接着上次继续」）。
    """
    d = load_ws()

    def _int(v, default=0):
        try:
            return int(str(v).strip())
        except Exception:
            return default

    done = _int(d.get("batch_last_done"), 0)
    span = _int(d.get("batch_last_span"), 0)
    at = str(d.get("batch_last_at") or "")
    return {"done": done, "span": span, "at": at,
            "ok": done > 0 and bool(at)}


def next_run_range(default_span: int = 5) -> Optional[tuple]:
    """「接着上次继续」应该跑哪一段。

    Returns:
        ``(start, end)``；从没记录过则返回 None。
        下一段长度沿用上次的段长（没记录就用 ``default_span``）。
    """
    r = last_run()
    if not r["ok"]:
        return None
    start = r["done"] + 1
    span = r["span"] if r["span"] > 0 else max(1, int(default_span))
    return (start, start + span - 1)


def describe() -> str:
    """给日志/界面用的一行摘要。"""
    d = load_ws()
    np_ = d.get("novel_path") or "（无）"
    bk = d.get("book_name") or "（无）"
    s = f"小说={Path(np_).name if np_ != '（无）' else np_}  作品={bk}"
    if d.get("auto_accept"):
        s += (f"  自动采纳={d.get('min_words') or 2100}"
              f"~{d.get('max_words') or 2300}字")
    if d.get("review_req"):
        s += (f"  审稿={d.get('review_card') or '智慧版-6A'}"
              f"/{d['review_req'][:12]}")
        if d.get("review_instruction"):
            n = d['review_instruction'].count("\n") + 1
            s += f"+提示词({n}行)"
        if d.get("review_chapter"):
            s += f"@章节[{d['review_chapter']}]"
    return s


def last_novel() -> Optional[str]:
    """上次的小说路径（存在且文件真的在才返回）。"""
    p = load_ws().get("novel_path")
    if p and Path(p).exists():
        return p
    return None

"""把小说全文按章拆开（通用，覆盖中文小说常见写法）。

本文件由原巨型模块拆分而来（Phase C2/C1），拆分时按 AST 依赖做了拓扑排序，
每个模块只 import 排在自己前面的模块，不存在循环引用。
"""

from __future__ import annotations

from typing import List, Optional
import re

from xyxbot.novel.chapter import Chapter
from xyxbot.novel.patterns import CHAPTER_EN_RE, CHAPTER_RE, SPECIAL_RE, clean_text, cn_to_int

__all__ = ["_collect_candidates", "_make_title", "split_novel"]


# ---------------------------------------------------------------- 分章

def _collect_candidates(text: str) -> List[dict]:
    """扫全文，把三条模式命中的行都收进来（含位置，供排序/切片）。

    三条模式互有重叠的可能性（比如「第1章」既能被中文模式命中、
    也不会被英文模式命中），所以这里用**起始位置**去重，先到先得。
    """
    items: List[dict] = []
    seen_start: set[int] = set()

    def _add(m: "re.Match", num: Optional[int], title_rest: str,
             kind: str) -> None:
        if m.start() in seen_start:
            return
        seen_start.add(m.start())
        items.append({
            "start": m.start(),
            "end": m.end(),
            "no": num,
            "rest": title_rest,
            "kind": kind,
        })

    # 1) 第N章 / 第N回 …（编号第 1 组，单位第 2 组，标题第 3 组）
    for m in CHAPTER_RE.finditer(text):
        _add(m, cn_to_int(m.group(1)), m.group(3) or "", "num")
    # 2) 序章 / 楔子 / 番外 …（标记第 1 组，标题第 2 组）
    for m in SPECIAL_RE.finditer(text):
        _add(m, None, (m.group(1) or "") + " " + (m.group(2) or ""),
             "special")
    # 3) Chapter N（编号第 1 组，标题第 2 组）
    for m in CHAPTER_EN_RE.finditer(text):
        _add(m, cn_to_int(m.group(1)), m.group(2) or "", "en")

    items.sort(key=lambda x: x["start"])
    return items



def _make_title(x: dict, no: int) -> str:
    """给一条候选生成展示用标题。"""
    rest = clean_text(x.get("rest") or "")
    # ★ 剥掉标题前导的**收括号**：`【第1章】标题` 这种，正则的收括号可选项
    #   会和 lookahead 打架（回溯后 `】` 落进标题），这里统一擦掉。
    rest = re.sub(r"^[】\]）)」』》]+", "", rest).strip()
    if x.get("kind") == "special":
        # 特殊章：rest 里已经含「序章 / 番外 …」，直接沿用
        title = rest.strip()
        if not title:
            title = "序章"
        return title
    title = f"第{no}章"
    if rest:
        title += f" {rest}"
    return title



def split_novel(text: str) -> List[Chapter]:
    """把小说全文按章拆开（**通用**，覆盖中文小说常见写法）。

    返回 [Chapter, ...]；一章都没识别到则返回空列表。

    兼容写法见文件顶部「分章正则」注释。核心是**整行命中**：
    正文里随口提到的「第1章」不会被误当成标题。
    """
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    # 顺手去掉 BOM（有些 Windows 记事本另存会带 \ufeff）
    text = text.lstrip("\ufeff")

    items = _collect_candidates(text)
    if not items:
        return []

    # 按位置切正文
    raw_items = []
    for i, x in enumerate(items):
        start = x["end"]
        end = items[i + 1]["start"] if i + 1 < len(items) else len(text)
        body = clean_text(text[start:end])
        raw_items.append({
            "no": x["no"],
            "rest": x["rest"],
            "kind": x["kind"],
            "body": body,
        })

    # ★ 过滤「目录残留」：没有任何正文的条目直接丢掉
    #    （一本小说的目录页会连着出现几十行「第N章」，每行后面都没有正文）
    raw_items = [x for x in raw_items if x["body"]]
    if not raw_items:
        return []

    # ★★ 章号归一（关键，别搞错）：
    #   目标是「第N章」的 N 尽量等于**原书里的章号** —— 用户填细纲、
    #   圈定跑章范围（第 3~10 章）都是按原书章号说的，串位就全错。
    #
    #   规则（简单且可预测）：
    #     A. **全是编号章**，且编号严格递增不重复 → **原样用书里的号**
    #        （99% 的小说都是这种，尤其是本站导出的 txt）
    #     B. 只要**混进了特殊章**（序章/楔子/番外…），或编号有**重复/倒序**
    #        → 整本改成顺序编号 1,2,3…
    #        理由：有特殊章的书，号本来就不规整（序章 + 第1章 该谁当 #1？），
    #        强行对齐只会让「第3章」在软件里变成「第4章」，更坑用户。
    #        顺序编号保证：唯一、连续、不串位。
    numbered = [x["no"] for x in raw_items if x["no"]]
    has_special = any(not x["no"] for x in raw_items)
    book_num_ok = True
    seen: set = set()
    last = 0
    for n in numbered:
        if n in seen or n <= last:
            book_num_ok = False
            break
        seen.add(n)
        last = n

    use_book_num = book_num_ok and numbered and not has_special

    chapters: List[Chapter] = []
    for i, x in enumerate(raw_items):
        no = x["no"] if (use_book_num and x["no"]) else (i + 1)
        chapters.append(Chapter(no=no,
                                title=_make_title(x, no),
                                body=x["body"]))

    return chapters

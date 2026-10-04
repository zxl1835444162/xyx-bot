"""小说分章 + 短代号模板（#1 / #2 / ...）。

把一部小说的 .txt 全文拆成「一章一个短代号」，供 UI 里的输入框填写细纲。

★ 核心设计（用户需求）：
    每一章 = 一个**短代号**，形如 `#1` `#2` `#3`（代表你在输入框里填的细纲）

    然后你可以写一段**指令模板**，把代号嵌进自然语言里：

        根据 #1 的细纲，续写下一段正文，保持爽文节奏。前文脉络参考 #2。

    程序会把 `#1` 替换成第 1 章输入框里的细纲，`#2` 同理，得到最终文本。

兼容写法（都认）：
    #1    #1     [1]     第1章      {{第1章}}

「关联章节」（最近10章）不在这里处理 —— 那是站点弹窗里的选项，
由 ai.py 在浏览器里点。

用法：
    from src.novel import NovelProject

    proj = NovelProject.load("C:/.../开局被绿.txt")
    proj.chapters               # [Chapter(no=1, code="#1", title=..., body=...)]
    proj.tokens()               # ["#1", "#2", ...]
    proj.set_note(1, "陆晨发现被绿…")
    proj.render_template("根据 #1 的细纲续写正文，参考 #2")
    # → "根据 陆晨发现被绿… 的细纲续写正文，参考 …"
    proj.save("proj.json") / NovelProject.open("proj.json")
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Optional

# ---------------------------------------------------------------- 分章正则
#
# ★★★ 用户需求（2026-10-04）：
#   「为啥这个 txt 的分章功能，不能把他分出来？这也太草台班子了，
#     我想做成**通用的**，而不是定制的」
#
#   根因：旧正则的行首空白类只有 `[ \t]`，**不含全角空格 U+3000**。
#   而中文小说/微信导出的 txt 里，章节标题极常见地写成
#       `　　第1章 订婚前夜的背叛`   （两个全角空格 = 段落缩进）
#   ⇒ 一篇 101 章的小说，**一章都分不出来**。
#
#   所以这次不再是「打补丁多加一个字符」，而是重写成**多模式通用解析器**：
#     * 行首空白：半角空格 / 制表符 / **全角空格** / 不换行空格，任意混合
#     * 章节标记：第N章 / 第N回 / 第N节 / 第N话 / 第N卷… 以及「序章/楔子/
#       引子/前言/尾声/番外」这类**无编号**特殊章
#     * 包裹符号：【第1章】 / `第1章` / **第1章** / ## 第1章 / 第1章 标题
#     * 数字：阿拉伯数字 / 中文数字 / 前导零（第001章）
#     * 全角标点：：、．－　以及半角 : . -
#
#   设计要点：**每条模式必须整行命中（match + $）**，避免把正文里
#   偶然出现的「第1章」当成标题 —— 这是分章最容易出错的地方。

# 行首允许的空白：半角空格、制表符、全角空格(U+3000)、不换行空格
_LEAD = r"[ \t\u3000\u00a0]*"
# 行尾允许的空白（同样含全角）
_TAIL = r"[ \t\u3000\u00a0]*"
# 「第 1 章」中间允许穿插的空白
_GAP = r"[ \t\u3000\u00a0]*"
# 行内的「非换行空白」（含全角空格）—— 用于「标题前必须有分隔」
_WS = r"[ \t\u3000\u00a0]"
# 数字部分：阿拉伯 或 中文数字
_NUM = r"[0-9０-９一二三四五六七八九十百千万零两〇]+"
# 章 / 回 / 节 / 话 / 卷 / 集 / 篇 —— 中文小说常见的分节单位
_UNIT = r"[章回节话卷集篇]"
# 章号与标题之间**必须出现**的分隔符。
#
# ★★ 这里的「必须有」是分章正确性的关键：
#     如果分隔符可以为空，「第一章正文。」这种**正文行**也会整行命中
#     （`第一章` + 空分隔 + `正文。`），于是正文被误当成新章的标题，
#     真正的章节标题反而因为 body 为空被过滤掉 —— 整本书一章都分不出来。
#     ⇒ 所以：`第1章标题`（黏着）**不算**标题行，
#       `第1章 标题` / `第1章：标题` / `第1章、标题` 才算。
#
# ★ 用法：用 **lookahead 断言**「章号后面要么行尾、要么是分隔符」，
#   断言**不消耗字符**，于是标题捕获组能原样拿到「《龙之传说》杀青」
#   （左书名号不会被吃掉）。
#   合法分隔：空白 / 标点 / 开引号 / **收括号**（`【第1章】标题` 的 `】`）。
_SEP_LOOKAHEAD = (r"(?=" + _WS + r"|$|[：:、.．。\-—－~～·]|"
                  + r"[《〈「『“\"'‘【\[（(】\]）)」』])")
# 标题前**允许被吃掉**的分隔符：空白 + 标点（冒号顿号等）。
# ★ 为什么标点也要吃掉：否则 `第1章：标题` 会变成 `第1章 ：标题`（多一个冒号），
#   用户看到的标题就不干净了。
# ★ 但**开引号不能吃**（`第98章《龙之传说》` 的左书名号要留在标题里）。
_SEP_SKIP = r"[：:、.．。\-—－~～· \t\u3000\u00a0]*"
# 标题内容：不含换行、不含裸星号
_TITLE = r"[^\n*]*?"

CN_NUM = {c: i for i, c in enumerate("零一二三四五六七八九十")}
CN_NUM.update({"两": 2, "百": 100, "千": 1000, "万": 10000, "〇": 0})


def _cn_num_re_group() -> str:
    """中文数字**字符类**内容（用于正则，务必配 `[...]` 使用）。

    ★★ 注意：这里返回的是**字符集合**的成员，使用方必须写成字符类
       `[<这些字符>]`。写成捕获组 `(...)` 是错的 —— 那样会被解释成
       「这一串字符的**字面顺序**」，`(零一二三)` 只匹配子串 "零一二三"。
       这个坑曾让 `Chapter 十二` 一条都匹配不上。
    """
    return "".join(CN_NUM.keys())


# ---------------- 模式 1：带编号的「第N章」类（主力） ----------------
# 允许的变体：
#   　　第1章 订婚前夜的背叛     ## 第1章 标题     **第1章 标题**
#   【第001章】标题              第 1 章 标题      第1章：标题
#   第十二回 大闹天宫            第3节 尾声        第2话 觉醒
#   第1章                        （只有章号，没有标题）
CHAPTER_RE = re.compile(
    # 行首空白 + 可选 markdown 井号 + 可选加粗星号 + 可选开括号
    rf"^{_LEAD}(?:#{{1,6}}{_GAP})?(?:\*\*)?{_GAP}[【\[（(「『]?{_GAP}"
    # 第 + 数字 + 单位（章/回/节/话/卷/集/篇）
    rf"第{_GAP}({_NUM}){_GAP}({_UNIT})"
    # 可选收括号
    rf"{_GAP}[】\]）)」』]?"
    # ★ 断言：后面必须是「行尾 或 分隔符」，否则不算标题行（防正文误伤）
    rf"{_SEP_LOOKAHEAD}"
    # 标题（可选）：先吃掉中间的分隔符空白，再抓标题正文
    rf"{_SEP_SKIP}({_TITLE})"
    # 可选闭合加粗星号
    rf"{_GAP}(?:\*\*)?{_TAIL}$",
    re.MULTILINE,
)

# ---------------- 模式 2：无编号的特殊章（序章 / 楔子 / 番外 …） ----------------
# 这类章没有「第N章」，但确实是一章的开头。
#   序章 / 楔子 / 引子 / 前言 / 序 / 尾声 / 后记 / 番外 / 终章 / 大结局
# 允许带标题：序章 雪夜 / 番外一 番外的故事
# ★ 同样要求：标记后面要么结束，要么有分隔符，避免「序章的故事」这种正文行
#   被误判（正文里出现「序章」二字）。
SPECIAL_WORDS = ("序章", "楔子", "引子", "前言", "序言", "尾声", "尾章",
                 "后记", "终章", "大结局", "番外篇", "番外", "外传",
                 "人物设定", "作者的话", "卷首语")
# ★ 说明：**没有**单独列 `序` —— 它太常见（"顺序""次序"…），
#   单开一行概率极低，收进来只会带来误伤。`序言`/`序章` 已覆盖绝大多数。
SPECIAL_RE = re.compile(
    rf"^{_LEAD}(?:#{{1,6}}{_GAP})?(?:\*\*)?{_GAP}[【\[（(「『]?{_GAP}"
    rf"(序章|楔子|引子|前言|序言|尾声|尾章|后记|终章|大结局|"
    rf"番外篇|番外|外传|人物设定|作者的话|卷首语)"
    rf"{_GAP}[】\]）)」』]?"
    rf"{_SEP_LOOKAHEAD}"
    rf"{_SEP_SKIP}({_TITLE})"
    rf"{_GAP}(?:\*\*)?{_TAIL}$",
    re.MULTILINE,
)

# ---------------- 模式 3：英文 Chapter N（兼容翻译稿） ----------------
# 数字用**贪婪** `+`（不是 `+?`），否则「Chapter 十二」只会吃到「十」。
# ★ 中文数字必须是**字符类** `[...]`，不能写成 `(...)`（见 _cn_num_re_group 说明）。
CHAPTER_EN_RE = re.compile(
    rf"^{_LEAD}(?:#{{1,6}}{_GAP})?(?:\*\*)?{_GAP}"
    rf"(?:Chapter|CHAPTER|chapter){_WS}+([0-9]+|[{_cn_num_re_group()}]+)"
    rf"{_SEP_LOOKAHEAD}"
    rf"{_SEP_SKIP}({_TITLE})"
    rf"{_GAP}(?:\*\*)?{_TAIL}$",
    re.MULTILINE,
)


def cn_to_int(s: str) -> Optional[int]:
    """把「一 / 十二 / 二十三」这类中文数字转成 int；纯数字直接返回。"""
    s = s.strip()
    if s.isdigit():
        return int(s)
    if not s or any(ch not in CN_NUM for ch in s):
        return None

    # 简化处理：支持「十」「二十」「二十三」「一百」等常见形式
    total = 0
    section = 0
    number = 0
    for ch in s:
        v = CN_NUM[ch]
        if v < 10:
            number = v
        elif v == 10:
            section += (number or 1) * 10
            number = 0
        else:  # 百千万
            section = (section + (number or 1)) * v
            total += section
            section = 0
            number = 0
    return total + section + number


def clean_text(t: str) -> str:
    """去掉 markdown 加重符号、HTML 注释和多余空白。"""
    t = re.sub(r"<!--.*?-->", "", t, flags=re.S)   # HTML 注释
    t = re.sub(r"\*\*(.+?)\*\*", r"\1", t)         # **粗体**
    t = re.sub(r"^#{1,6}\s*", "", t, flags=re.M)   # 标题井号
    t = re.sub(r"[ \t\u3000]+", " ", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


# ---------------------------------------------------------------- 数据结构

@dataclass
class Chapter:
    """一个章节。"""
    no: int                      # 章序号（1 开始）
    title: str                   # 原始标题行，如「第1章 订婚前夜的背叛」
    body: str = ""               # 章节正文（去掉标题行）
    note: str = ""               # ★ 用户在 UI 里填的「这一章细纲/剧情」
    prefix: str = ""             # ★ 单章前缀（一般不用，全局前缀就够）
    suffix: str = ""             # ★ 单章后缀

    @property
    def code(self) -> str:
        """★ 本章的短代号，如 `#1`。写指令时用它。"""
        return f"#{self.no}"

    @property
    def token(self) -> str:
        """兼容旧写法，等同 code。"""
        return self.code

    @property
    def full_text(self) -> str:
        return f"{self.title}\n\n{self.body}".strip()

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Chapter":
        return cls(
            no=int(d.get("no", 0)),
            title=str(d.get("title", "")),
            body=str(d.get("body", "")),
            note=str(d.get("note", "")),
            prefix=str(d.get("prefix", "")),
            suffix=str(d.get("suffix", "")),
        )


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


# ---------------------------------------------------------------- 项目

@dataclass
class NovelProject:
    """一部小说的分章结果 + 用户填写内容 + 指令模板。"""
    name: str = ""
    source: str = ""                                  # 源 txt 路径
    chapters: List[Chapter] = field(default_factory=list)

    # 全局模板（对所有章都生效，可被单章覆盖）
    global_prefix: str = ""
    global_suffix: str = ""

    # ★ 指令模板：可嵌入 #1 #2 …，替换后就是要送进站点的文本
    #   例："根据 #1 的细纲续写正文，前文参考 #2。"
    instruction: str = "#1"

    # 生成时：用户没填内容的章，用「代号原文」还是「原文正文」
    fallback_to_body: bool = True

    # -------------------------------------------------- 载入 / 保存

    @classmethod
    def load(cls, txt_path: str | Path,
             name: Optional[str] = None) -> "NovelProject":
        """从 .txt 分章。"""
        p = Path(txt_path)
        if not p.exists():
            raise FileNotFoundError(f"找不到文件：{p}")

        raw = p.read_text(encoding="utf-8-sig", errors="ignore")
        chapters = split_novel(raw)
        proj = cls(
            name=name or p.stem,
            source=str(p),
            chapters=chapters,
        )
        print(f"[novel] 已分章：《{proj.name}》 共 {len(chapters)} 章")
        return proj

    def save(self, path: str | Path) -> None:
        """存成 .json（含用户填写的内容）。"""
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "name": self.name,
            "source": self.source,
            "global_prefix": self.global_prefix,
            "global_suffix": self.global_suffix,
            "instruction": self.instruction,
            "fallback_to_body": self.fallback_to_body,
            "chapters": [c.to_dict() for c in self.chapters],
        }
        p.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                     encoding="utf-8")
        print(f"[novel] 已保存：{p}")

    @classmethod
    def open(cls, path: str | Path) -> "NovelProject":
        """读回 .json。"""
        p = Path(path)
        data = json.loads(p.read_text(encoding="utf-8"))
        return cls(
            name=data.get("name", p.stem),
            source=data.get("source", ""),
            chapters=[Chapter.from_dict(d) for d in data.get("chapters", [])],
            global_prefix=data.get("global_prefix", ""),
            global_suffix=data.get("global_suffix", ""),
            instruction=data.get("instruction", "#1"),
            fallback_to_body=bool(data.get("fallback_to_body", True)),
        )

    # -------------------------------------------------- ★ 轻量记忆（sidecar）
    #
    # ★★ 用户需求（2026-10-04）：
    #     「我导入的东西是否具有记忆功能 —— 上次填的，下次不用费劲巴拉继续填」
    #
    #   为什么不用 `save()` 而是另做一个 sidecar：
    #     `save()` 会把每一章的 `body`（小说正文）一起写进去，文件大小和
    #     txt 差不多（实测用户那本 100 章 ≈ 0.16MB）。
    #     而启动时真正需要"记住"的只有**用户自己敲进去的东西**：细纲、
    #     指令模板、前后缀。
    #     小说正文可以从 txt **重新分章**得到 —— 实测 0.16MB / 100 章只要 5ms，
    #     完全可以每次启动重来。所以 sidecar 只存"人填的部分"：
    #       * 只有几 KB
    #       * 永远不会和 txt 不一致（txt 改了也不会读到过期正文）
    #
    #   用户那本实测：`有细纲的章数 = 0` —— 也就是说他暂时没填细纲，
    #   但 `#@` 会回退成该章原文（`fallback_to_body=True`），所以
    #   "启动时要能把分章结果恢复出来"这件事**直接影响每章发出去的剧情**。

    def sidecar_dict(self) -> dict:
        """只含「人填的东西」的轻量字典（不含小说正文）。"""
        from datetime import datetime

        return {
            "txt_path": self.source or "",
            "name": self.name,
            "instruction": self.instruction,
            "global_prefix": self.global_prefix,
            "global_suffix": self.global_suffix,
            "fallback_to_body": bool(self.fallback_to_body),
            # 只存**非空**细纲：空的就是"没填"，不必占地方
            "notes": {str(c.no): c.note
                      for c in self.chapters if c.note.strip()},
            "chapter_count": len(self.chapters),
            "saved_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

    def save_sidecar(self, path: str | Path) -> bool:
        """把「人填的部分」存下来（几 KB，可频繁调用）。"""
        try:
            p = Path(path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(
                json.dumps(self.sidecar_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8")
            return True
        except Exception as e:
            print(f"[novel] 保存轻量记忆失败：{e}")
            return False

    @classmethod
    def restore_sidecar(cls, path: str | Path) -> Optional["NovelProject"]:
        """按 sidecar 恢复：**重新分章** + 套回细纲 / 模板 / 前后缀。

        Returns:
            恢复好的工程；txt 已不在 / sidecar 读不出来 → None
            （调用方据此退回"还没载入"的状态，不要报错吵用户）。
        """
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except Exception:
            return None
        if not isinstance(data, dict):
            return None
        src = str(data.get("txt_path") or "").strip()
        if not src or not Path(src).exists():
            return None
        try:
            proj = cls.load(src, name=(data.get("name") or None))
        except Exception as e:
            print(f"[novel] 恢复上次的小说失败：{e}")
            return None

        proj.instruction = str(data.get("instruction") or proj.instruction)
        proj.global_prefix = str(data.get("global_prefix") or "")
        proj.global_suffix = str(data.get("global_suffix") or "")
        proj.fallback_to_body = bool(data.get("fallback_to_body", True))

        notes = data.get("notes") or {}
        if isinstance(notes, dict):
            for k, v in notes.items():
                try:
                    proj.set_note(int(str(k)), str(v))
                except Exception:
                    continue
        return proj

    # -------------------------------------------------- 短代号

    def tokens(self) -> List[str]:
        """全部短代号，如 ['#1', '#2', ...]。"""
        return [c.code for c in self.chapters]

    def code_map(self) -> dict:
        """{代号: Chapter}，如 {'#1': Chapter(1)}。"""
        return {c.code: c for c in self.chapters}

    def find(self, key) -> Optional[Chapter]:
        """按代号 / 章号找章节。

        支持：#1  #1  [1]  {{第1章}}  第1章  1
        """
        if isinstance(key, int):
            for c in self.chapters:
                if c.no == key:
                    return c
            return None

        t = str(key).strip()
        m = (re.fullmatch(r"#\s*(\d+)", t)
             or re.fullmatch(r"\[\s*(\d+)\s*\]", t)
             or re.fullmatch(r"\{\{第(\d+)章\}\}", t)
             or re.fullmatch(r"第(\d+)章", t)
             or re.fullmatch(r"(\d+)", t))
        if not m:
            return None
        no = int(m.group(1))
        for c in self.chapters:
            if c.no == no:
                return c
        return None

    def set_note(self, key, text: str) -> bool:
        """给某一章设置细纲/剧情。key 同 find()。"""
        c = self.find(key)
        if c is None:
            return False
        c.note = text
        return True

    # -------------------------------------------------- 渲染

    def render(self, chapter: Chapter | int, text: Optional[str] = None,
               use_global: bool = True) -> str:
        """生成单章的最终文本：前缀 + 内容 + 后缀。

        Args:
            chapter:    Chapter 对象或章序号
            text:       要替换进代号的正文；None 则用 chapter.note
            use_global: 是否套用全局前后缀
        """
        c = chapter if isinstance(chapter, Chapter) else self.find(chapter)
        if c is None:
            return ""

        content = (text if text is not None else c.note) or ""
        if not content.strip():
            # 没填内容时的兜底
            content = c.body if self.fallback_to_body else c.code

        pre = "\n".join(x for x in [
            self.global_prefix if use_global else "",
            c.prefix,
        ] if x).strip()
        suf = "\n".join(x for x in [
            c.suffix,
            self.global_suffix if use_global else "",
        ] if x).strip()

        parts = [x for x in (pre, content, suf) if x]
        return "\n\n".join(parts)

    def render_all(self, use_global: bool = True) -> str:
        """把所有章拼成一份完整文本（代号全部替换掉）。"""
        out = []
        for c in self.chapters:
            out.append(self.render(c, use_global=use_global))
        return "\n\n".join(out)

    def render_with_tokens(self) -> str:
        """生成一份**保留代号**的模板文本，用于预览。

        例：
            #1
            #2
            ...
        """
        lines = []
        for c in self.chapters:
            pre = "\n".join(x for x in (self.global_prefix, c.prefix) if x).strip()
            suf = "\n".join(x for x in (c.suffix, self.global_suffix) if x).strip()
            block = "\n".join(x for x in (pre, c.code, suf) if x)
            lines.append(block)
        return "\n\n".join(lines)

    # -------------------------------------------------- 指令模板 ★

    # 匹配 #1 / #1 / [1] / {{第1章}} / 第1章
    CODE_RE = re.compile(
        r"(?<![\w#])(?:#\s*(\d+)"
        r"|(?<!\d)\[\s*(\d+)\s*\]"
        r"|\{\{第(\d+)章\}\})"
    )

    # ★★ 「当前章」占位符（批量跑章用）：#@ / {{当前章}} / {{本章}} / #当前章
    #   批量循环每跑一章，就把这个占位符替换成「当前正在生成的这一章」的细纲。
    #   与 #N（绝对章号）不同：写 #3 永远是第3章，#@ 才是「正在跑的那章」。
    CUR_RE = re.compile(r"#@|\{\{当前章\}\}|\{\{本章\}\}|#当前章")

    def render_template(self, template: Optional[str] = None,
                        mode: str = "note",
                        values: Optional[dict] = None,
                        current: Optional[int] = None) -> str:
        """★ 把指令模板里的 #1 #2 替换成对应章节的内容。

        Args:
            template: 指令模板；None 则用 self.instruction
            mode:     替换成什么
                       "note"     → 你填的细纲（没填则回退 body）  ★默认
                       "body"     → 该章原文正文
                       "title"    → 章节标题
                       "render"   → 前缀+细纲+后缀（见 render()）
                       "both"     → 「原文摘要 + 细纲」都带上
            values:   {代号或章号: 文本} 直接指定，优先级最高
            current:  ★ 当前章号（批量跑章用）。
                       非 None 时，模板里的「当前章」占位符
                       `#@` / `{{当前章}}` / `{{本章}}` / `#当前章`
                       会被替换成**这一章**的内容（mode 同 #N 的逻辑）。

        Returns:
            替换后的最终文本
        """
        tpl = self.instruction if template is None else template
        if not tpl:
            return ""

        def _pick(no: int) -> str:
            # values 优先（支持 '#1' / '1' 两种键）
            if values:
                for k in (f"#{no}", str(no), no):
                    if k in values:
                        return str(values[k])
            c = self.find(no)
            if c is None:
                return ""
            if mode == "body":
                return c.body
            if mode == "title":
                return c.title
            if mode == "render":
                return self.render(c)
            if mode == "both":
                head = c.body[:200].strip()
                note = c.note.strip()
                return "\n".join(x for x in (
                    f"【{c.title} 原文节选】\n{head}" if head else "",
                    f"【本章细纲】\n{note}" if note else "",
                ) if x)
            # 默认 note
            return c.note.strip() or (c.body if self.fallback_to_body else "")

        # ★★ 先替换「当前章」占位符（#@ → 第 current 章的内容）
        if current is not None:
            cur_text = _pick(int(current))
            tpl = self.CUR_RE.sub(cur_text, tpl)

        def _sub(m: "re.Match") -> str:
            g = m.group(1) or m.group(2) or m.group(3)
            if not g:
                return m.group(0)
            c = self.find(int(g))
            if c is None:
                # ★ 不存在的代号：原样保留，方便发现写错了
                return m.group(0)
            return _pick(int(g))

        out = self.CODE_RE.sub(_sub, tpl)

        # 多遍替换：支持细纲里再出现别的代号
        for _ in range(3):
            if not self.CODE_RE.search(out):
                break
            out = self.CODE_RE.sub(_sub, out)
        return out

    def render_for_batch(self, no: int, template: Optional[str] = None,
                         mode: str = "note") -> str:
        """★ 批量跑章用：把模板渲染成「第 no 章」的剧情。

        与 `render_template(current=no)` 的区别（2026-10-04 用户反馈）：
          用户模板末尾常写 `#1`（单章用法残留），批量跑章时 `#1` 会**永远**
          引用第1章 → 每一章都用了第1章的细纲（「一直定在第一章」）。
          本方法：如果模板里**没有** `#@`（当前章占位符），就把 `#N` 也当作
          「当前章」——自动把 `#1`/`#2`/… 转成 `#@`，再按第 no 章渲染。
          模板里**有** `#@` 时，行为等同 `render_template(current=no)`。

        用法（批量跑章时）：
            plot_for = lambda no: proj.render_for_batch(no)
        """
        tpl = self.instruction if template is None else template
        if tpl and self.CUR_RE.search(tpl) is None:
            # ★ 根因修复（未知代号被错误地当成「当前章」）：
            #   原实现直接把**所有** `#N` 一律 `CODE_RE.sub("#@")`。
            #   于是越界代号（如 `#99`，第99章不存在）也变成 `#@`，
            #   结果被渲染成**当前章**的细纲 —— 用户写错了代号却毫无提示，
            #   还会把错误内容悄悄送进站点。
            #   现在只把**存在的**代号转成 `#@`；不存在的原样保留，
            #   由 `render_template` 的既有语义处理（原样保留 + 这里告警）。
            unknown = [n for n in self._code_numbers(tpl)
                       if self.find(n) is None]
            if unknown:
                print(f"[novel] ⚠ 指令模板里有不存在的代号 "
                      f"{' '.join(f'#{n}' for n in unknown)}"
                      f"（共 {len(self.chapters)} 章）——"
                      f"这些代号会原样保留，请检查模板是否写错")
            tpl = self.CODE_RE.sub(
                lambda m: "#@" if self.find(
                    int(m.group(1) or m.group(2) or m.group(3))) else m.group(0),
                tpl)
        return self.render_template(tpl, mode=mode, current=no)

    def _code_numbers(self, template: str) -> List[int]:
        """列出模板里出现的全部代号章号（去重、保序）。"""
        out: List[int] = []
        for m in self.CODE_RE.finditer(template or ""):
            g = m.group(1) or m.group(2) or m.group(3)
            if not g:
                continue
            n = int(g)
            if n not in out:
                out.append(n)
        return out

    def template_preview(self, limit: int = 400) -> str:
        """把 instruction 渲染一下，超长则截断（给 UI 预览用）。"""
        txt = self.render_template()
        if len(txt) > limit:
            return txt[:limit] + f"\n…（共 {len(txt)} 字）"
        return txt

    def check_template(self, template: Optional[str] = None) -> dict:
        """检查指令模板里的代号：哪些没定义、哪些没填细纲。

        Returns:
            {
              "unknown": [999, ...],      # 模板里写了但不存在的章号
              "empty":   [3, 7, ...],     # 存在但还没填细纲的章号
              "used":    [1, 2, 10],      # 模板里用到的章号
              "ok":      bool             # 没有任何问题
            }
        """
        tpl = self.instruction if template is None else template
        used: List[int] = []
        unknown: List[int] = []
        for m in self.CODE_RE.finditer(tpl or ""):
            g = m.group(1) or m.group(2) or m.group(3)
            if not g:
                continue
            no = int(g)
            if no not in used:
                used.append(no)
            c = self.find(no)
            if c is None and no not in unknown:
                unknown.append(no)

        empty = []
        for no in used:
            c = self.find(no)
            if c is not None and not c.note.strip():
                empty.append(no)

        return {
            "unknown": sorted(unknown),
            "empty": sorted(empty),
            "used": used,
            "ok": not unknown and not empty,
        }

    # -------------------------------------------------- 进度

    def progress(self) -> dict:
        """填写进度：填了几章 / 共几章。"""
        total = len(self.chapters)
        filled = sum(1 for c in self.chapters if c.note.strip())
        return {"total": total, "filled": filled,
                "percent": round(filled / total * 100) if total else 0}

    def summary(self) -> str:
        p = self.progress()
        return (f"《{self.name}》 {p['total']} 章"
                f"（已填 {p['filled']} 章，{p['percent']}%）")


# ---------------------------------------------------------------- CLI 便捷

def main():
    import sys
    if len(sys.argv) < 2:
        print("用法: python -m src.novel <小说.txt> [指令模板]")
        print('例:   python -m src.novel 开局被绿.txt "根据 #1 的细纲续写正文"')
        sys.exit(1)
    proj = NovelProject.load(sys.argv[1])
    print(f"\n{proj.summary()}\n")
    for c in proj.chapters[:10]:
        print(f"  {c.code:6s} {c.title:32s} {len(c.body)} 字")
    if len(proj.chapters) > 10:
        print(f"  ... 还有 {len(proj.chapters) - 10} 章")

    # 演示短代号模板
    proj.set_note(1, "陆晨撞见女友与经纪人王浩私会，怒火中烧，系统激活。")
    tpl = sys.argv[2] if len(sys.argv) > 2 else \
        "根据 #1 的细纲，续写下一段正文，保持爽文节奏。"
    print(f"\n--- 指令模板 ---\n{tpl}")
    print(f"\n--- 替换后 ---\n{proj.render_template(tpl)}")


if __name__ == "__main__":
    main()

"""Chapter：一章的数据（正文 / 细纲 / 前缀后缀）。

本文件由原巨型模块拆分而来（Phase C2/C1），拆分时按 AST 依赖做了拓扑排序，
每个模块只 import 排在自己前面的模块，不存在循环引用。
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict

__all__ = ["Chapter"]


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

"""构建信息（打包时由 CI 覆盖写入，方便远程确认"你装的是哪个版本"）。

VERSION 的唯一真相源是 `xyxbot/version.py`；CI 只覆盖 `SHA` 与 `BUILT_AT`。
本地开发时这两个保持 "dev"。
"""

from __future__ import annotations

from xyxbot.version import VERSION  # noqa: F401  单一真相源，此处不再重复定义

SHA = "dev"
BUILT_AT = "dev"


def describe() -> str:
    """一行说明，给 --selftest 与诊断报告用。"""
    return f"v{VERSION} build={SHA} at={BUILT_AT}"

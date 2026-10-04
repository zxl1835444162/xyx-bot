# -*- coding: utf-8 -*-
"""构建信息（打包时由 CI 覆盖写入，方便远程确认"你装的是哪个版本"）。

CI 会在 PyInstaller 之前把真实的 git SHA 与构建时间写进这个文件；
本地开发时保留 "dev"。
"""

from __future__ import annotations

SHA = "dev"
BUILT_AT = "dev"
VERSION = "1.0.0"


def describe() -> str:
    """一行说明，给 --selftest 和诊断报告用。"""
    return f"v{VERSION} build={SHA} at={BUILT_AT}"

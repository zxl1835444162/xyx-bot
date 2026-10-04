"""凭据存储：记住账号密码。

存储位置：artifacts/storage/credentials.json
密码用「机器相关密钥 + 简单异或混淆」保存 —— 注意这**不是强加密**，
只能防止一眼看到明文，不能防御有意的逆向。本地工具场景够用。
界面上会明确提示用户这一点。
"""

from __future__ import annotations

import base64
import getpass
import hashlib
import json
import os
import platform
from pathlib import Path
from typing import Optional

from . import config as C

CRED_FILE = C.STORAGE / "credentials.json"


def _machine_key() -> bytes:
    """生成与当前机器/用户绑定的密钥，换机器就解不开。"""
    seed = "|".join([
        platform.node(),
        getpass.getuser(),
        platform.system(),
        "zhaoshi-xingyue-studio",
    ])
    return hashlib.sha256(seed.encode("utf-8")).digest()


def _xor(data: bytes) -> bytes:
    key = _machine_key()
    return bytes(b ^ key[i % len(key)] for i, b in enumerate(data))


def _encrypt(text: str) -> str:
    if not text:
        return ""
    return base64.urlsafe_b64encode(_xor(text.encode("utf-8"))).decode("ascii")


def _decrypt(token: str) -> str:
    if not token:
        return ""
    try:
        return _xor(base64.urlsafe_b64decode(token.encode("ascii"))).decode("utf-8")
    except Exception:
        return ""


# ---------------------------------------------------------------- 读写

def save(username: str, password: str, remember: bool = True) -> None:
    """保存凭据。remember=False 时清除已存内容。"""
    try:
        CRED_FILE.parent.mkdir(parents=True, exist_ok=True)
        if not remember:
            data = {"remember": False}
        else:
            data = {
                "remember": True,
                "username": username,
                "password": _encrypt(password),
            }
        CRED_FILE.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        try:
            os.chmod(CRED_FILE, 0o600)
        except Exception:
            pass
    except Exception as e:
        print(f"[cred] 保存凭据失败: {e}")


def load() -> dict:
    """读取凭据。返回 {remember, username, password}。"""
    empty = {"remember": False, "username": "", "password": ""}
    if not CRED_FILE.exists():
        return empty
    try:
        data = json.loads(CRED_FILE.read_text(encoding="utf-8"))
    except Exception:
        return empty

    if not data.get("remember"):
        return empty

    return {
        "remember": True,
        "username": data.get("username", ""),
        "password": _decrypt(data.get("password", "")),
    }


def clear() -> None:
    """清除已保存的凭据。"""
    try:
        if CRED_FILE.exists():
            CRED_FILE.unlink()
    except Exception as e:
        print(f"[cred] 清除凭据失败: {e}")


def has_saved() -> bool:
    return load().get("remember", False)

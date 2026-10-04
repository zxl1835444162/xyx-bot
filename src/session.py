"""站点登录态管理：把「登录一次，长期免登录」这件事做扎实。

背景
----
星月写作的登录态存在 cookie + localStorage 里。Playwright 的
`storage_state` 能把这两样一次性导出成 JSON，下次启动浏览器时直接注入，
效果等同于「你已经登录过了」——不用再扫码 / 输密码。

本模块负责这个 state 文件的生命周期：

    save_from_context(ctx)  登录成功后导出
    exists()                有没有存过
    load()                  读出来（给 browser.new_context 用）
    describe()              给 UI 看的摘要（时间 / 条数 / 登录账号）
    clear()                 登出

顺带把「怎么算登录成功」这件事收口在这里，UI 和 CLI 共用一套判断。
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from . import config as C

# 登录态文件（cookie + localStorage）
STATE_FILE: Path = C.STATE_FILE

# 备份文件：保存新 state 前先留一份旧的，避免写坏了没得退
BACKUP_FILE: Path = C.STORAGE / "state.backup.json"


# ---------------------------------------------------------------- 读写

def exists() -> bool:
    """是否已保存过登录态。"""
    try:
        return STATE_FILE.is_file() and STATE_FILE.stat().st_size > 2
    except Exception:
        return False


def state_path_for_playwright() -> Optional[str]:
    """给 browser.new_context(storage_state=...) 用的路径。

    文件不存在时返回 None —— Playwright 对 None 的处理就是「全新会话」，
    正好是我们想要的语义（未登录）。
    """
    return str(STATE_FILE) if exists() else None


def load() -> dict:
    """读出 state 字典。读不到返回 {}。"""
    if not exists():
        return {}
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[session] 读取登录态失败: {e}")
        return {}


def save_from_context(context) -> bool:
    """从 Playwright BrowserContext 导出登录态并落盘。

    必须在「已经登录成功」之后调用，否则存下来的是一份未登录的废文件。
    """
    if context is None:
        print("[session] 上下文为空，跳过保存")
        return False

    try:
        C.STORAGE.mkdir(parents=True, exist_ok=True)

        # 先备份旧的（如果存在）
        if exists():
            try:
                BACKUP_FILE.write_bytes(STATE_FILE.read_bytes())
            except Exception:
                pass

        context.storage_state(path=str(STATE_FILE))

        # 记一下保存时间，UI 要显示
        meta = _read_meta()
        meta["saved_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        meta["cookies"] = _count_cookies()
        meta["account"] = _guess_account(context)
        _write_meta(meta)

        try:
            os.chmod(STATE_FILE, 0o600)
        except Exception:
            pass

        print(f"[session] ✓ 登录态已保存（{meta['cookies']} 条 cookie）")
        return True
    except Exception as e:
        print(f"[session] ✗ 保存登录态失败: {e}")
        return False


def clear() -> None:
    """清除登录态（登出）。"""
    removed = []
    for p in (STATE_FILE, META_FILE, BACKUP_FILE):
        try:
            if p.exists():
                p.unlink()
                removed.append(p.name)
        except Exception as e:
            print(f"[session] 删除 {p.name} 失败: {e}")
    print(f"[session] 已清除登录态: {', '.join(removed) or '（本就没有）'}")


# ---------------------------------------------------------------- 元信息

META_FILE: Path = C.STORAGE / "session_meta.json"


def _read_meta() -> dict:
    try:
        if META_FILE.is_file():
            return json.loads(META_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _write_meta(meta: dict) -> None:
    try:
        META_FILE.write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception:
        pass


def _count_cookies() -> int:
    data = load()
    return len(data.get("cookies") or [])


def _guess_account(context) -> str:
    """尽力猜一下登录账号，猜不到就留空。

    ★ 根因修复（恒为空）：
      实测磁盘上的 `state.json` 显示，星月写作把用户信息放在
      **`userStorage`** 键里（结构为 `{"data":{"userInfo":{...}}}`），
      而原实现只扫 `userInfo` / `user` / `account` / `nickName` 等**扁平**键
      → 永远匹配不到，`session_meta.json` 的 `account` 实测恒为空串。

      现在：
        ① 候选键加入 `userStorage`（站点真实键名）
        ② 解析时**递归**找常见字段，兼容 `data.userInfo.xxx` 这种嵌套
    """
    try:
        val = context.pages[0].evaluate(
            """() => {
                const WANT = ['nickName','nickname','username','userName',
                              'name','account','mobile','phone','uid','id'];
                // 深度优先找第一个命中的字段（兼容任意嵌套）
                function dig(o, depth) {
                    if (!o || typeof o !== 'object' || depth > 4) return '';
                    for (const k of WANT) {
                        const v = o[k];
                        if (v !== undefined && v !== null && String(v).trim()) {
                            return String(v).trim();
                        }
                    }
                    for (const k of Object.keys(o)) {
                        const r = dig(o[k], depth + 1);
                        if (r) return r;
                    }
                    return '';
                }
                // ★ userStorage 是实测的站点真实键名
                const keys = ['userStorage','userInfo','user_info','user',
                              'account','username','nickName','userData'];
                for (const k of keys) {
                    const raw = localStorage.getItem(k);
                    if (!raw) continue;
                    try {
                        const o = JSON.parse(raw);
                        const v = dig(o, 0);
                        if (v) return v;
                    } catch (e) {
                        if (raw.length < 40) return raw;
                    }
                }
                return '';
            }"""
        )
        return str(val or "")
    except Exception:
        return ""


# ---------------------------------------------------------------- 给 UI 的摘要

def describe() -> dict:
    """返回登录态摘要，供界面展示。

    {
        "saved": bool,          # 有没有存过
        "saved_at": str,        # 保存时间
        "cookies": int,         # cookie 条数
        "account": str,         # 猜到的账号（可能为空）
        "path": str,            # 文件路径
        "size": str,            # 文件大小（人类可读）
    }
    """
    if not exists():
        return {
            "saved": False, "saved_at": "", "cookies": 0,
            "account": "", "path": str(STATE_FILE), "size": "-",
        }

    meta = _read_meta()
    try:
        size = STATE_FILE.stat().st_size
        size_s = f"{size / 1024:.1f} KB" if size >= 1024 else f"{size} B"
    except Exception:
        size_s = "-"

    return {
        "saved": True,
        "saved_at": meta.get("saved_at") or _mtime_str(),
        "cookies": meta.get("cookies") or _count_cookies(),
        "account": meta.get("account", ""),
        "path": str(STATE_FILE),
        "size": size_s,
    }


def _mtime_str() -> str:
    try:
        ts = STATE_FILE.stat().st_mtime
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return ""


def age_text() -> str:
    """登录态有多久了，用于提示「可能快过期了」。"""
    if not exists():
        return ""
    try:
        ts = STATE_FILE.stat().st_mtime
        delta = datetime.now() - datetime.fromtimestamp(ts)
        days = delta.days
        if days <= 0:
            hours = int(delta.total_seconds() // 3600)
            return f"{hours} 小时前" if hours > 0 else "刚刚"
        return f"{days} 天前"
    except Exception:
        return ""

"""管理ポータルの簡易パスワード認証。src/admin/app.py から使用。

ADMIN_PASSWORD でログインし、HMAC 署名付きの有効期限トークンを Cookie に持たせる。
外部依存を増やさないため署名は stdlib（hmac/hashlib）で実装する。
"""

from __future__ import annotations

import hashlib
import hmac
import os
import time

_DEFAULT_TTL = 86400  # 24時間


def _secret() -> bytes:
    """署名鍵。ADMIN_SESSION_SECRET 優先、無ければ ADMIN_PASSWORD から導出。"""
    base = os.environ.get("ADMIN_SESSION_SECRET") or (
        "sess:" + os.environ.get("ADMIN_PASSWORD", "")
    )
    return hashlib.sha256(base.encode()).digest()


def password_ok(password: str) -> bool:
    """入力パスワードが ADMIN_PASSWORD と一致するか（未設定なら常に不許可）。"""
    expected = os.environ.get("ADMIN_PASSWORD")
    if not expected:
        return False
    return hmac.compare_digest(password, expected)


def make_token(ttl_seconds: int = _DEFAULT_TTL) -> str:
    """有効期限付きの署名トークンを発行する（"exp.signature" 形式）。"""
    exp = str(int(time.time()) + ttl_seconds)
    sig = hmac.new(_secret(), exp.encode(), hashlib.sha256).hexdigest()
    return f"{exp}.{sig}"


def verify_token(token: str | None) -> bool:
    """トークンの署名と有効期限を検証する。"""
    if not token or "." not in token:
        return False
    exp_str, sig = token.rsplit(".", 1)
    try:
        exp = int(exp_str)
    except ValueError:
        return False
    if exp < time.time():
        return False
    expected = hmac.new(_secret(), exp_str.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(sig, expected)

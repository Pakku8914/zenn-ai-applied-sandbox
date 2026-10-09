"""練習問題2の解答：Authorization ヘッダから Bearer のトークンを取り出し、定数時間で照合する。"""

from __future__ import annotations

import hashlib
import hmac


def parse_bearer(value: str | None) -> str | None:
    """'Bearer <token>' の token を返す。方式名は大文字小文字を区別しない。形が違えば None。"""
    if not value:
        return None
    scheme, _, token = value.strip().partition(" ")
    token = token.strip()
    if scheme.lower() != "bearer" or not token or " " in token:
        return None
    return token


def key_matches(presented: str, stored_hash: str) -> bool:
    """提示されたキーのハッシュと保存したハッシュを、比較にかかる時間が中身に依存しない方法で比べる。"""
    digest = hashlib.sha256(presented.encode("utf-8")).hexdigest()
    return hmac.compare_digest(digest, stored_hash)

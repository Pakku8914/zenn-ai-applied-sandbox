"""練習問題1の解答：保存する行と、利用者に1回だけ見せる平文を分けて作る。"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime


def new_key_record(user_id: str, now: datetime) -> tuple[str, dict]:
    """(平文のキー, DB に保存する行) を返す。行には平文を入れない。"""
    key = "kd_" + secrets.token_urlsafe(32)
    record = {
        "user_id": user_id,
        "prefix": key[:8],
        "key_hash": hashlib.sha256(key.encode("utf-8")).hexdigest(),
        "created_at": now,
    }
    return key, record


def display_hint(record: dict) -> str:
    """一覧画面に出す見分け用の表記（例：kd_AbCdE…）。行の情報だけで作れる。"""
    return f"{record['prefix']}…"

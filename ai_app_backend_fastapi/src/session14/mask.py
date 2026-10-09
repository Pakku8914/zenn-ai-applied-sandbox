"""ログに残す前に、個人情報（PII）と秘密情報を伏せる（マスク）。

- 取りこぼさない側に倒す。多少の伏せすぎは許し、伏せ忘れは許さない
- 前後の境界は ASCII の文字だけで判定する。正規表現の「単語の文字」は日本語も含むので、
  それを境界に使うと「電話は09012345678」のように日本語に続く番号を見逃す
- API キーは、照合用の KEY_PATTERN（session09：kd_ + ちょうど43文字）より緩くする。途中で切れたキーも伏せたい
"""

from __future__ import annotations

import re
from collections.abc import Mapping

REDACTED = "[REDACTED]"

BEARER = re.compile(r"(?i)(?<![A-Za-z])(bearer\s+)[^\s\"',]+")
SK_KEY = re.compile(r"(?<![A-Za-z0-9_-])(sk-(?:ant-)?)[A-Za-z0-9_-]{16,}")
KD_KEY = re.compile(r"(?<![A-Za-z0-9_-])kd_[A-Za-z0-9_-]{16,}")
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")
PHONE = re.compile(r"(?<![0-9A-Za-z_+-])(?:\+81[- ]?\d{1,4}|0\d{1,4})[- ]?\d{1,4}[- ]?\d{4}(?![0-9A-Za-z_-])")

# 名前だけで中身を伏せる項目（値の形に関係なく [REDACTED] にする）
SECRET_KEYS = frozenset({"authorization", "cookie", "password", "api_key", "x-api-key"})


def mask_text(text: str) -> str:
    text = BEARER.sub(rf"\1{REDACTED}", text)  # Bearer の後ろは、キーの形でなくても伏せる
    text = SK_KEY.sub(rf"\1{REDACTED}", text)  # sk-ant-… / sk-…（上流のキー）
    text = KD_KEY.sub(lambda m: m.group(0)[:8] + "…", text)  # 自前のキーは先頭8文字だけ残す（session09 と同じ）
    text = EMAIL.sub("[EMAIL]", text)
    return PHONE.sub("[PHONE]", text)


def mask_value(value: object) -> object:
    """文字列は伏せ、辞書と配列は中までたどる。数値・真偽値・None はそのまま。"""
    if isinstance(value, str):
        return mask_text(value)
    if isinstance(value, Mapping):
        return mask_fields(value)
    if isinstance(value, (list, tuple)):
        return [mask_value(v) for v in value]
    return value


def mask_fields(fields: Mapping[str, object]) -> dict[str, object]:
    return {k: REDACTED if str(k).lower() in SECRET_KEYS else mask_value(v) for k, v in fields.items()}

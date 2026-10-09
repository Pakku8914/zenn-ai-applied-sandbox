"""ログに残す前に、個人情報（PII）と秘密情報を伏せる（session14/mask.py のコピー）。"""

from __future__ import annotations

import re
from collections.abc import Mapping

REDACTED = "[REDACTED]"

BEARER = re.compile(r"(?i)(?<![A-Za-z])(bearer\s+)[^\s\"',]+")
SK_KEY = re.compile(r"(?<![A-Za-z0-9_-])(sk-(?:ant-)?)[A-Za-z0-9_-]{16,}")
KD_KEY = re.compile(r"(?<![A-Za-z0-9_-])kd_[A-Za-z0-9_-]{16,}")
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")
PHONE = re.compile(r"(?<![0-9A-Za-z_+-])(?:\+81[- ]?\d{1,4}|0\d{1,4})[- ]?\d{1,4}[- ]?\d{4}(?![0-9A-Za-z_-])")

SECRET_KEYS = frozenset({"authorization", "cookie", "password", "api_key", "x-api-key"})


def mask_text(text: str) -> str:
    text = BEARER.sub(rf"\1{REDACTED}", text)
    text = SK_KEY.sub(rf"\1{REDACTED}", text)
    text = KD_KEY.sub(lambda m: m.group(0)[:8] + "…", text)
    text = EMAIL.sub("[EMAIL]", text)
    return PHONE.sub("[PHONE]", text)


def mask_value(value: object) -> object:
    if isinstance(value, str):
        return mask_text(value)
    if isinstance(value, Mapping):
        return mask_fields(value)
    if isinstance(value, (list, tuple)):
        return [mask_value(v) for v in value]
    return value


def mask_fields(fields: Mapping[str, object]) -> dict[str, object]:
    return {k: REDACTED if str(k).lower() in SECRET_KEYS else mask_value(v) for k, v in fields.items()}

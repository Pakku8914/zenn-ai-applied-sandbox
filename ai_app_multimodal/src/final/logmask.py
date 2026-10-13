"""ログのマスク（セッション13の logmask.py の写し）。SAFE_KEYS に source を足しただけ。

メッセージは固定のイベント名にし、値は extra={"fields": {...}} で渡す。許可したキーの文字列・数値だけをそのまま出し、
それ以外は「種類・長さ・SHA256 の先頭12桁」に畳む。例外は種類の名前だけにする。
"""

from __future__ import annotations

import hashlib
import logging

SAFE_KEYS = frozenset({
    "user_id", "request_id", "upload_id", "document_id", "receipt_id", "voice_id",
    "kind", "bytes", "chars", "pages", "audio_seconds", "sha12", "store_audio", "error",
    "uploads", "documents", "receipts", "voice", "usage", "source",
})
FORMAT = "%(levelname)s %(name)s %(message)s%(fields_text)s"


def sha12(data: bytes | str) -> str:
    raw = data.encode("utf-8") if isinstance(data, str) else bytes(data)
    return hashlib.sha256(raw).hexdigest()[:12]


def fold(value: object) -> object:
    if isinstance(value, (bytes, bytearray, memoryview)):
        return f"<bytes len={len(value)} sha={sha12(bytes(value))}>"
    if isinstance(value, str):
        return f"<text chars={len(value)} sha={sha12(value)}>"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return f"<{type(value).__name__}>"


def keep(key: str, value: object) -> bool:
    return key in SAFE_KEYS and (value is None or isinstance(value, (str, bool, int, float)))


class MaskFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if getattr(record, "masked", False):
            return True
        fields = dict(getattr(record, "fields", None) or {})
        masked = {k: v if keep(k, v) else fold(v) for k, v in fields.items()}
        if record.args:
            args = record.args
            record.args = {k: fold(v) for k, v in args.items()} if isinstance(args, dict) else tuple(map(fold, args))
        if record.exc_info:
            masked["error"] = record.exc_info[0].__name__ if record.exc_info[0] else "unknown"
            record.exc_info, record.exc_text = None, None
        record.fields = masked
        record.fields_text = "".join(f" {k}={v}" for k, v in masked.items())
        record.masked = True
        return True


def masked_handler(handler: logging.Handler | None = None) -> logging.Handler:
    handler = handler or logging.StreamHandler()
    handler.addFilter(MaskFilter())
    handler.setFormatter(logging.Formatter(FORMAT))
    return handler


def setup_logging(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        logger.addHandler(masked_handler())
        logger.setLevel(logging.INFO)
        logger.propagate = False
    return logger

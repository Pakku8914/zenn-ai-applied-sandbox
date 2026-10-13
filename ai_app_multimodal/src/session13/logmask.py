"""ログのマスク（セッション13）。画像・音声のバイト列・文字起こし・ファイル名の中身をログに残さない。

書き方の約束：メッセージは固定のイベント名にし、値は extra={"fields": {...}} で渡す。
MaskFilter は安全網として、次のように畳む。
- 許可したキー（ID・長さ・種類・件数）の文字列・数値だけをそのまま出す
- それ以外のキーの値と、%s で埋め込まれた値（record.args）は「種類・長さ・SHA256 の先頭12桁」にする
- 例外の詳細（メッセージや traceback に入力値が入りうる）は出さず、例外の種類の名前だけにする
Filter はロガーではなくハンドラに付ける（子のロガーから伝わってきた記録にも効かせるため）。
"""

from __future__ import annotations

import hashlib
import logging

SAFE_KEYS = frozenset({
    "user_id", "request_id", "upload_id", "document_id", "receipt_id", "voice_id",
    "kind", "bytes", "chars", "pages", "audio_seconds", "sha12", "store_audio", "error",
    "uploads", "documents", "receipts", "voice", "usage",
})
FORMAT = "%(levelname)s %(name)s %(message)s%(fields_text)s"


def sha12(data: bytes | str) -> str:
    raw = data.encode("utf-8") if isinstance(data, str) else bytes(data)
    return hashlib.sha256(raw).hexdigest()[:12]


def fold(value: object) -> object:
    """中身を「種類・長さ・SHA256 の先頭12桁」に畳む。数値・真偽値・None はそのまま。"""
    if isinstance(value, (bytes, bytearray, memoryview)):
        return f"<bytes len={len(value)} sha={sha12(bytes(value))}>"
    if isinstance(value, str):
        return f"<text chars={len(value)} sha={sha12(value)}>"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return f"<{type(value).__name__}>"   # 辞書・リスト・オブジェクトは中身を出さない


def keep(key: str, value: object) -> bool:
    """そのまま出してよいか：許可したキーで、値が文字列・数値・真偽値・None のときだけ。"""
    return key in SAFE_KEYS and (value is None or isinstance(value, (str, bool, int, float)))


class MaskFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if getattr(record, "masked", False):   # ハンドラが複数あっても、畳むのは1回だけ
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
    """ハンドラに MaskFilter と書式を付けて返す（既定は標準エラー出力）。"""
    handler = handler or logging.StreamHandler()
    handler.addFilter(MaskFilter())
    handler.setFormatter(logging.Formatter(FORMAT))
    return handler


def setup_logging(name: str) -> logging.Logger:
    """name のロガー（と、その子のロガー）の記録を、マスクしてから出す。2回呼んでもハンドラは増えない。"""
    logger = logging.getLogger(name)
    if not logger.handlers:
        logger.addHandler(masked_handler())
        logger.setLevel(logging.INFO)
        logger.propagate = False        # ルートのハンドラ（マスクしない）に二重に流さない
    return logger

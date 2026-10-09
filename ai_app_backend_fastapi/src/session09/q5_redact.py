"""練習問題5の解答：うっかりログに混ざったキーを伏せる「最後の砦」のフィルタ。"""

from __future__ import annotations

import logging
import re

KEY_RE = re.compile(r"kd_[A-Za-z0-9_-]{43}")
BEARER_RE = re.compile(r"(?i)\b(bearer\s+)\S+")


def redact(text: str) -> str:
    text = BEARER_RE.sub(r"\1***", text)  # Bearer の後ろは、キーの形でなくても伏せる
    return KEY_RE.sub(lambda m: m.group(0)[:8] + "…", text)


class RedactSecrets(logging.Filter):
    """メッセージ（%s の引数を埋めた後）と例外の本文から、キーと Bearer の値を伏せる。"""

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact(record.getMessage())
        record.args = None  # 埋め終わった文に置き換えたので、引数はもう使わない
        if record.exc_info and not record.exc_text:
            record.exc_text = logging.Formatter().formatException(record.exc_info)
        if record.exc_text:
            record.exc_text = redact(record.exc_text)
        return True


def install_redaction(handler: logging.Handler) -> logging.Handler:
    """フィルタはハンドラに付ける（ロガーに付けると、子のロガーから伝わってきた記録には効かない）。"""
    handler.addFilter(RedactSecrets())
    return handler

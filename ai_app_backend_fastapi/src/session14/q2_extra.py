"""問題2の解答：extra のキーが LogRecord の属性や JSON の基本キーと重なっても、落ちず・消えない log_event()。

logger.info("x", extra={"name": ...}) は KeyError（Attempt to overwrite 'name' in LogRecord）で落ちる。
extra={"event": ...} は落ちないが、JsonFormatter が基本キーを優先するので黙って消える。
"""

from __future__ import annotations

import logging
from collections.abc import Mapping

from .jsonlog import RESERVED

BASE_KEYS = frozenset({"ts", "level", "logger", "event", "request_id", "job_id", "exc_type", "exc"})
TAKEN = RESERVED | BASE_KEYS


def safe_fields(fields: Mapping[str, object]) -> dict[str, object]:
    return {f"field_{k}" if k in TAKEN else k: v for k, v in fields.items()}


def log_event(logger: logging.Logger, level: int, event: str, /, **fields: object) -> None:
    """位置専用引数（/）にしたので、fields に event や level という名前があっても引数とぶつからない。"""
    logger.log(level, event, extra=safe_fields(fields), stacklevel=2)  # funcName・lineno は呼び出し元を指す

"""標準 logging で、1件を JSON 1行にする（session16/jsonlog.py のコピー。既定のロガー名だけ変えた）。"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime
from typing import TextIO

from kondate.clock import JST

from .logctx import job_id_var, request_id_var
from .mask import mask_fields, mask_text

RESERVED = frozenset(vars(logging.makeLogRecord({}))) | {"message", "asctime"}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        data: dict[str, object] = {
            "ts": datetime.fromtimestamp(record.created, JST).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "event": mask_text(record.getMessage()),
        }
        for key, var in (("request_id", request_id_var), ("job_id", job_id_var)):
            value = var.get()
            if value is not None:
                data[key] = value
        extra = {k: v for k, v in vars(record).items() if k not in RESERVED and k not in data}
        data.update(mask_fields(extra))
        if record.exc_info and record.exc_info[0] is not None:
            data["exc_type"] = record.exc_info[0].__name__
            data["exc"] = mask_text(self.formatException(record.exc_info))
        return json.dumps(data, ensure_ascii=False, default=str)


def setup_json_logging(name: str = "kondate.final", *, level: int | str = "INFO",
                       stream: TextIO | None = None) -> logging.Handler:
    """name のロガーに JSON の出力先を1つだけ付ける。何度呼んでも出力先は増えない。"""
    log = logging.getLogger(name)
    for old in [h for h in log.handlers if isinstance(h.formatter, JsonFormatter)]:
        log.removeHandler(old)
    handler = logging.StreamHandler(stream or sys.stdout)
    handler.setFormatter(JsonFormatter())
    log.addHandler(handler)
    log.setLevel(level)
    log.propagate = False
    return handler

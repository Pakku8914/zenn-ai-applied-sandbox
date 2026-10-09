"""標準ライブラリの logging だけで、1件を JSON 1行で出す（追加ライブラリなし）。

キーの並び：ts・level・logger・event（必ず）→ request_id・job_id（文脈にあれば）→ extra で渡した項目
            → 例外があれば exc_type・exc
event と extra の文字列はマスクしてから出す。ts・level・logger・request_id・job_id は自分で作った値なので伏せない。
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime
from typing import TextIO

from kondate.clock import JST

from .logctx import job_id_var, request_id_var
from .mask import mask_fields, mask_text

# LogRecord が最初から持つ属性。これ以外の属性が extra で渡された項目
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
        # 基本キーと重なる extra は捨てる（文脈の値が優先。文脈に無いときだけ extra の request_id・job_id を使う）
        extra = {k: v for k, v in vars(record).items() if k not in RESERVED and k not in data}
        data.update(mask_fields(extra))
        if record.exc_info and record.exc_info[0] is not None:
            data["exc_type"] = record.exc_info[0].__name__
            data["exc"] = mask_text(self.formatException(record.exc_info))
        # ensure_ascii=False：日本語をそのまま／default=str：Decimal や datetime も文字列にして落とさない
        return json.dumps(data, ensure_ascii=False, default=str)


def setup_json_logging(name: str = "kondate.session14", *, level: int | str = "INFO",
                       stream: TextIO | None = None) -> logging.Handler:
    """name のロガーに JSON の出力先を1つだけ付ける。何度呼んでも出力先は増えない。"""
    log = logging.getLogger(name)
    for old in [h for h in log.handlers if isinstance(h.formatter, JsonFormatter)]:
        log.removeHandler(old)
    handler = logging.StreamHandler(stream or sys.stdout)
    handler.setFormatter(JsonFormatter())
    log.addHandler(handler)
    log.setLevel(level)
    log.propagate = False  # root（uvicorn・Celery が設定する）へ渡して、別の形式で二重に出さない
    return handler

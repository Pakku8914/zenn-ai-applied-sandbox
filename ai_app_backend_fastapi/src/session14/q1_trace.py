"""問題1の解答：JSON 1行のログから、1つの request_id に関わる行だけを時刻順に取り出す。"""

from __future__ import annotations

import json
from collections.abc import Iterable


def parse_lines(lines: Iterable[str]) -> list[dict]:
    """JSON として読める行だけを辞書にする。uvicorn・Celery の普通の行や、壊れた行は飛ばす。"""
    records: list[dict] = []
    for line in lines:
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict):
            records.append(record)
    return records


def trace(lines: Iterable[str], request_id: str) -> list[dict]:
    """request_id が一致する行を ts の順に並べる（同じ +09:00 の ISO 8601 なら、文字列の順＝時刻の順）。"""
    hits = [r for r in parse_lines(lines) if r.get("request_id") == request_id]
    return sorted(hits, key=lambda r: r.get("ts", ""))  # sorted は安定：同じ時刻なら出てきた順のまま


def upstream_request_ids(records: Iterable[dict]) -> list[str]:
    """上流への問い合わせに使う ID（取れなかった呼び出しの null は除く）。"""
    return [r["upstream_request_id"] for r in records if r.get("upstream_request_id")]


def publish_headers(request_id: str | None) -> dict:
    """apply_async がメッセージを送る直前と同じく before_task_publish を送り、受け手が足したヘッダを返す。"""
    # 上の3つはどこでも動く調査道具にしたいので、Celery の import はこの関数の中だけに閉じる
    from celery.signals import before_task_publish

    from . import tasks  # noqa: F401  import すると本文の attach_request_id がシグナルにつながる
    from .logctx import request_id_var

    headers: dict = {}
    token = request_id_var.set(request_id)
    try:
        before_task_publish.send(sender="s14.plan_week", body=None, exchange="", routing_key="celery",
                                 headers=headers, properties={}, declare=[], retry_policy=None)
    finally:
        request_id_var.reset(token)
    return headers

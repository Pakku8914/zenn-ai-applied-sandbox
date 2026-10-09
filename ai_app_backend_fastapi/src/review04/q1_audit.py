"""問題1：障害時の JSON ログと台帳を request_id で突き合わせる（セッション14 × セッション13 × セッション6）。

- audit()：stream_closed の行ごとに台帳を引き、「台帳の値が見積もりの行（estimated）」と「台帳に行が無い（missing）」を挙げる。
  台帳の outcome（cancelled など4種）では分からない本当の理由（drained・failed など）は、ログの reason から取る
- backfill_records()：usage_record_failed の行から、台帳に足し直す UsageRecord を作る（同じ request_id は1件にまとめる）
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

from .metering import UsageRecord
from .providers import Usage


@dataclass(frozen=True)
class LedgerRow:
    request_id: str
    usage_source: str
    outcome: str
    input_tokens: int
    output_tokens: int


@dataclass(frozen=True)
class Finding:
    request_id: str
    kind: str  # estimated（台帳の値は見積もり）/ missing（台帳に行が無い）
    reason: str  # stream_closed の reason（completed / failed / drained / cancelled）
    input_tokens: int
    output_tokens: int


def parse_lines(lines: Iterable[str]) -> list[dict]:
    """JSON 1行のログだけを取り出す。uvicorn の素の行や、途中で切れた行は読み飛ばす。"""
    out: list[dict] = []
    for raw in lines:
        line = raw.strip()
        if not line.startswith("{"):
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and isinstance(data.get("event"), str):
            out.append(data)
    return out


def audit(lines: Iterable[str], ledger: Iterable[LedgerRow]) -> list[Finding]:
    rows = {r.request_id: r for r in ledger}
    closed: dict[str, dict] = {}  # request_id → stream_closed の行（ログに出た順を保つ）
    for d in parse_lines(lines):
        if d["event"] == "stream_closed" and d.get("request_id"):
            closed.setdefault(d["request_id"], d)
    findings: list[Finding] = []
    for rid, d in closed.items():
        row = rows.get(rid)
        if row is None:
            findings.append(Finding(rid, "missing", d["reason"], d["input_tokens"], d["output_tokens"]))
        elif row.usage_source == "estimated":
            findings.append(Finding(rid, "estimated", d["reason"], row.input_tokens, row.output_tokens))
    return findings


def backfill_records(lines: Iterable[str]) -> list[UsageRecord]:
    """usage_record_failed の行（セッション13の save_quietly が全項目を残す）から、足し直す記録を作る。"""
    records: dict[str, UsageRecord] = {}
    for d in parse_lines(lines):
        if d["event"] != "usage_record_failed" or d["request_id"] in records:
            continue
        usage = Usage(d["input_tokens"], d["output_tokens"], d["cache_read_input_tokens"],
                      d["cache_creation_input_tokens"])
        records[d["request_id"]] = UsageRecord(d["request_id"], d["user_id"], d["model"],
                                               datetime.fromisoformat(d["started_at"]), usage,
                                               d["usage_source"], d["outcome"])
    return list(records.values())

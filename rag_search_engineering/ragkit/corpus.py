"""コーパス・クエリ・判定データの読み込み。

ファイルは tools/make_corpus.py が固定シードで生成する（決定的）。
"""

from __future__ import annotations

import json
from pathlib import Path

from .models import Doc, Query

CORPUS_DIR = Path(__file__).resolve().parent.parent / "corpus"


def _read_jsonl(path: str | Path) -> list[dict]:
    p = Path(path)
    if not p.is_absolute():
        p = CORPUS_DIR.parent / p
    if not p.exists():
        raise FileNotFoundError(
            f"{p} がありません。先に `python tools/make_corpus.py` を実行してください。"
        )
    with p.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def load_docs(path: str | Path = "corpus/docs.jsonl") -> list[Doc]:
    return [Doc(**row) for row in _read_jsonl(path)]


def load_queries(path: str | Path = "corpus/queries.jsonl") -> list[Query]:
    return [Query(**row) for row in _read_jsonl(path)]


def load_qrels(path: str | Path = "corpus/qrels.jsonl") -> dict[str, dict[str, int]]:
    """{query_id: {doc_id: grade}} の形で返す。grade は 0/1/2。"""
    qrels: dict[str, dict[str, int]] = {}
    for row in _read_jsonl(path):
        qrels.setdefault(row["query_id"], {})[row["doc_id"]] = int(row["grade"])
    return qrels

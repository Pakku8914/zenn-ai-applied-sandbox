"""Knowledge Bases の検索対象として使う、教材共通の小さな社内文書コーパス。

題材は本書全体で固定します（`requirements.md`「命名規約・共通シナリオ」参照）:
架空の会社「サンプル商事」の社内ヘルプデスク文書。業務知識の説明が要らず、
チャンキング・メタデータフィルタ・ハイブリッド検索の効果が見て分かる粒度にしてあります。
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from .generation import cosine, embed

CORPUS_PATH = Path(__file__).resolve().parent.parent / "fixtures" / "kb_corpus.json"


@lru_cache(maxsize=1)
def documents() -> list[dict]:
    with CORPUS_PATH.open(encoding="utf-8") as f:
        return json.load(f)


@lru_cache(maxsize=1)
def _indexed() -> list[tuple[dict, list[float]]]:
    return [(doc, embed(doc["text"], dimensions=1024)) for doc in documents()]


def _lexical_score(query: str, text: str) -> float:
    """キーワード一致の割合。ハイブリッド検索の「キーワード側」を担う。"""
    terms = [t for t in query.replace("　", " ").split() if t]
    if not terms:
        return 0.0
    hit = sum(1 for t in terms if t in text)
    return round(hit / len(terms), 6)


def search(
    query: str,
    *,
    top_k: int = 3,
    search_type: str = "SEMANTIC",
    metadata_filter: dict | None = None,
) -> list[dict]:
    """コーパスを検索して retrievalResults 相当のリストを返す。

    - `SEMANTIC`：埋め込みのコサイン類似度のみ
    - `HYBRID`：コサイン類似度とキーワード一致を 0.7 : 0.3 で合成
    """
    query_vec = embed(query, dimensions=1024)
    results: list[dict] = []
    for doc, vec in _indexed():
        if metadata_filter and not _matches(doc, metadata_filter):
            continue
        semantic = cosine(query_vec, vec)
        if search_type.upper() == "HYBRID":
            score = round(0.7 * semantic + 0.3 * _lexical_score(query, doc["text"]), 6)
        else:
            score = semantic
        results.append(
            {
                "content": {"type": "TEXT", "text": doc["text"]},
                "location": {
                    "type": "S3",
                    "s3Location": {"uri": doc["uri"]},
                },
                "score": score,
                "metadata": {
                    "title": doc["title"],
                    "category": doc["category"],
                    "updatedAt": doc["updatedAt"],
                    "x-amz-bedrock-kb-source-uri": doc["uri"],
                },
            }
        )
    results.sort(key=lambda r: -r["score"])
    return results[:top_k]


def _matches(doc: dict, metadata_filter: dict) -> bool:
    """Knowledge Bases のフィルタ構文のうち、教材で使う演算子だけを解釈する。"""
    if "equals" in metadata_filter:
        cond = metadata_filter["equals"]
        return doc.get(cond["key"]) == cond["value"]
    if "notEquals" in metadata_filter:
        cond = metadata_filter["notEquals"]
        return doc.get(cond["key"]) != cond["value"]
    if "greaterThanOrEquals" in metadata_filter:
        cond = metadata_filter["greaterThanOrEquals"]
        return str(doc.get(cond["key"], "")) >= str(cond["value"])
    if "in" in metadata_filter:
        cond = metadata_filter["in"]
        return doc.get(cond["key"]) in cond["value"]
    if "andAll" in metadata_filter:
        return all(_matches(doc, f) for f in metadata_filter["andAll"])
    if "orAll" in metadata_filter:
        return any(_matches(doc, f) for f in metadata_filter["orAll"])
    return True

"""評価指標を自分の手で書く（セッション2 練習問題6の完成コード）。

ragkit.eval と同じ結果になることを src/session02/verify.py が突き合わせて検証する。
写経ではなく「定義から書ける」ことを確かめるための実装。
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ragkit.models import Hit  # noqa: E402


def to_doc_ranking(hits: list[Hit]) -> list[str]:
    """チャンク単位の順位を、順序を保ったまま文書単位に畳む。

    判定データ（qrels）は文書単位なので、この畳み込みを忘れると
    「同じ文書の 3 チャンクを 3 件と数える」水増しが起きる。
    """
    seen: set[str] = set()
    ranking: list[str] = []
    for hit in hits:
        if hit.doc_id and hit.doc_id not in seen:
            seen.add(hit.doc_id)
            ranking.append(hit.doc_id)
    return ranking


def recall_at_k(hits: list[Hit], qrels: dict[str, int], k: int = 10) -> float:
    """適合文書のうち上位 k 件で拾えた割合。分母は「拾うべき文書の総数」。"""
    relevant = {doc_id for doc_id, grade in qrels.items() if grade >= 1}
    if not relevant:
        return 0.0
    found = set(to_doc_ranking(hits)[:k])
    return len(relevant & found) / len(relevant)


def precision_at_k(hits: list[Hit], qrels: dict[str, int], k: int = 10) -> float:
    """上位 k 件のうち適合していた割合。分母は「実際に返した件数」。"""
    if k <= 0:
        return 0.0
    ranking = to_doc_ranking(hits)[:k]
    if not ranking:
        return 0.0
    return sum(1 for doc_id in ranking if qrels.get(doc_id, 0) >= 1) / len(ranking)


def mrr(hits: list[Hit], qrels: dict[str, int]) -> float:
    """最初の適合文書の順位の逆数。1 件も無ければ 0。"""
    for rank, doc_id in enumerate(to_doc_ranking(hits), start=1):
        if qrels.get(doc_id, 0) >= 1:
            return 1.0 / rank
    return 0.0


def dcg(gains: list[float]) -> float:
    """順位 i の利得を log2(i + 1) で割って足す（下位ほど価値を割り引く）。"""
    return sum(gain / math.log2(rank + 1) for rank, gain in enumerate(gains, start=1))


def ndcg_at_k(hits: list[Hit], qrels: dict[str, int], k: int = 10) -> float:
    """実際の DCG を、理想的な並びの DCG（iDCG）で割って 0〜1 に収める。"""
    ranking = to_doc_ranking(hits)[:k]
    gains = [float(qrels.get(doc_id, 0)) for doc_id in ranking]
    ideal = sorted((float(g) for g in qrels.values()), reverse=True)[:k]
    ideal_dcg = dcg(ideal)
    if ideal_dcg == 0.0:
        return 0.0
    return dcg(gains) / ideal_dcg

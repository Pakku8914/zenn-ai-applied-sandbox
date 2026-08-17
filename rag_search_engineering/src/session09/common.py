"""セッション9（リランク）の共通部品。

密ベクトルのコレクション minato_docs_fixed はセッション6・7で作ったものを再利用する。
無いときだけ作る（作り直さない）。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ragkit.chunk import chunk_all  # noqa: E402
from ragkit.corpus import load_docs, load_qrels, load_queries  # noqa: E402
from ragkit.dense import DenseIndex  # noqa: E402
from ragkit.eval import hits_to_docs  # noqa: E402
from ragkit.models import Hit  # noqa: E402

COLLECTION = "minato_docs_fixed"


def load_all():
    """docs / queries / qrels / chunks をまとめて読む（fixed(400/80)・673 チャンク）。"""
    docs = load_docs()
    queries = load_queries()
    qrels = load_qrels()
    chunks = chunk_all(docs, "fixed", size=400, overlap=80)
    return docs, queries, qrels, chunks


def dense_index(chunks: list | None = None) -> DenseIndex:
    idx = DenseIndex(COLLECTION)
    if not idx.client.collection_exists(COLLECTION):
        print(f"コレクション {COLLECTION} が無いので作成します（1分ほどかかります）")
        idx.build(chunks if chunks is not None else load_all()[3])
    return idx


def answerable(queries: list, qrels: dict) -> list:
    """適合文書が1件以上あるクエリだけを返す（回答不能クエリを除く）。"""
    return [q for q in queries if any(g >= 1 for g in qrels.get(q.query_id, {}).values())]


def first_of_type(queries: list, qrels: dict, qtype: str, n: int = 1) -> list:
    return [q for q in answerable(queries, qrels) if q.type == qtype][:n]


def relevant_docs(qr: dict[str, int]) -> set[str]:
    return {d for d, g in qr.items() if g >= 1}


def ceiling_recall(pool: list[Hit], qr: dict[str, int], k: int = 10) -> float:
    """候補プールから上位 k 件を選び直せたときに到達できる Recall@k の上限。

    リランクは並べ替えしかできないので、どれだけ賢くてもこの値を超えられない。
    """
    rel = relevant_docs(qr)
    if not rel:
        return 0.0
    found = len(rel & set(hits_to_docs(pool)))
    return min(found, k) / len(rel)


def rank_of(hits: list[Hit]) -> dict[str, int]:
    """chunk_id -> 1 始まりの順位。リランク前後の移動を見るために使う。"""
    return {h.chunk_id: i for i, h in enumerate(hits, start=1)}


def mark(qr: dict[str, int], doc_id: str) -> str:
    """適合（grade>=1）なら ◯、不適合なら × を返す。"""
    return "◯" if qr.get(doc_id, 0) >= 1 else "×"

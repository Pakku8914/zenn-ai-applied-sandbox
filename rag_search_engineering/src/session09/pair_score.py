#!/usr/bin/env python3
"""バイエンコーダとクロスエンコーダを、同じ (クエリ, 文書) の組で見比べる。

  1. 適合度の違う3件の文書に対する「コサイン類似度」と「クロスエンコーダのスコア」を並べる
  2. 文書ベクトルは使い回せる（索引化できる）が、クロスエンコーダのスコアは
     クエリが来るまで1つも計算できないことを、forward の回数で確認する

実行:  docker compose exec app python src/session09/pair_score.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import first_of_type, load_all, relevant_docs  # noqa: E402

from ragkit.dense import Embedder  # noqa: E402
from ragkit.rerank import CrossEncoderReranker  # noqa: E402


def pick_passages(docs, chunks, qrels, query):
    """適合度の違う3件のチャンクを決定的に選ぶ（完全適合 / 部分適合 / 無関係）。"""
    qr = qrels[query.query_id]
    doc_by_id = {d.doc_id: d for d in docs}
    first_chunk: dict[str, object] = {}
    for c in chunks:
        first_chunk.setdefault(c.doc_id, c)

    def by_grade(grade: int):
        for doc_id, g in sorted(qr.items()):
            if g == grade and doc_id in first_chunk:
                return first_chunk[doc_id]
        return None

    rel = relevant_docs(qr)
    rel_categories = {doc_by_id[d].category for d in rel if d in doc_by_id}
    unrelated = None
    for doc_id in sorted(first_chunk):
        if doc_id not in qr and doc_by_id[doc_id].category not in rel_categories:
            unrelated = first_chunk[doc_id]
            break

    picked = [("完全適合(grade=2)", by_grade(2)), ("部分適合(grade=1)", by_grade(1)),
              ("無関係(別カテゴリ)", unrelated)]
    return [(label, c) for label, c in picked if c is not None]


def main() -> None:
    docs, queries, qrels, chunks = load_all()
    query = first_of_type(queries, qrels, "natural")[0]
    labeled = pick_passages(docs, chunks, qrels, query)
    texts = [c.text for _, c in labeled]

    print(f"クエリ: {query.query_id} [{query.type}] {query.text}\n")

    # --- 1. 文書側の符号化は索引時に1度きり。クエリを知らずに先に計算できる -----
    t0 = time.perf_counter()
    doc_vecs = Embedder.encode_passages(texts)
    t_docs = (time.perf_counter() - t0) * 1000

    t0 = time.perf_counter()
    q_vec = Embedder.encode_query(query.text)
    t_query = (time.perf_counter() - t0) * 1000

    cos = [float(np.dot(q_vec, v)) for v in doc_vecs]

    # --- 2. クロスエンコーダは (クエリ, 文書) の組ごとに計算する -----------------
    model = CrossEncoderReranker.get()
    t0 = time.perf_counter()
    ce = [float(s) for s in model.predict([(query.text, t) for t in texts],
                                          show_progress_bar=False)]
    t_ce = (time.perf_counter() - t0) * 1000

    print(f"{'文書':<22}{'コサイン':>10}{'CEスコア':>12}  先頭30字")
    print("-" * 80)
    for (label, chunk), c, s in zip(labeled, cos, ce):
        head = chunk.text[:30].replace("\n", " ")
        print(f"{label:<22}{c:>10.4f}{s:>12.4f}  {head}")

    print(f"\nコサインの開き : {max(cos) - min(cos):.4f}")
    print(f"CEスコアの開き : {max(ce) - min(ce):.4f}")
    order = lambda vals: " > ".join(  # noqa: E731
        labeled[i][0] for i in sorted(range(len(vals)), key=lambda i: -vals[i]))
    print("順位（コサイン）: " + order(cos))
    print("順位（CE）      : " + order(ce))

    # --- 3. forward の回数（索引化できるかどうかの本質）--------------------------
    n_docs, n_queries = len(texts), 2
    print(f"\n所要時間: 文書{n_docs}件の符号化 {t_docs:.0f}ms / クエリ1件の符号化 {t_query:.0f}ms"
          f" / CE {n_docs}組の採点 {t_ce:.0f}ms")
    print("同じ文書集合に対してクエリを N 本さばくときの forward 回数")
    print(f"  バイエンコーダ  : 文書 {n_docs} 回（索引時に1度きり）+ クエリ N 回")
    print(f"  クロスエンコーダ: {n_docs} × N 回（クエリが来るまで1つも先に計算できない）")
    print(f"  例）N={n_queries} なら {n_docs + n_queries} 回 対 {n_docs * n_queries} 回。"
          "文書数が増えるほど差は開く")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""4つのチャンク方式を BM25 で比較する（セッション4）。

tools/eval_matrix.py --quick と同じ条件（同じコーパス・同じ検索器・同じ判定データ）で、
チャンク方式だけを入れ替える。埋め込みモデルを使わないので数十秒で終わる。

  python src/session04/compare_methods.py

「上位10件が何文書に畳み込まれるか」を知りたい場合は、chunk_lab.mean_folded_docs を
呼んで列を足すこと（練習問題の応用1）。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ragkit.chunk import chunk_all  # noqa: E402
from ragkit.corpus import load_docs, load_qrels, load_queries  # noqa: E402
from ragkit.eval import evaluate  # noqa: E402
from ragkit.lexical import LexicalIndex  # noqa: E402

K = 10
# チャンク方式とパラメータ。tools/eval_matrix.py と同じ値を使う（条件を揃えるため）
METHODS = {
    "fixed": dict(size=400, overlap=80),
    "sentence": dict(max_chars=400),
    "heading": dict(max_chars=600),
    "parent_window": dict(child=200, window=600),
}
QUERY_TYPES = ["abbrev", "keyword", "multi_condition", "natural", "temporal"]


def run(method: str, params: dict, docs, queries, qrels, k: int = K):
    """1方式を索引化して評価する。(EvalReport, チャンク数, 検索器) を返す。"""
    chunks = chunk_all(docs, method, **params)
    index = LexicalIndex().build(chunks)
    report = evaluate(index, queries, qrels, k=k, label=f"bm25 / {method}")
    return report, len(chunks), index


def main() -> None:
    docs, queries, qrels = load_docs(), load_queries(), load_qrels()

    rows = []
    for method, params in METHODS.items():
        report, n_chunks, _ = run(method, params, docs, queries, qrels)
        rows.append((method, report))
        print(f"{report.summary()}  [チャンク数 {n_chunks}]")

    # 桁を揃えた表は見た目が崩れやすいので、ラベル付きで1行1方式にする
    print("\n=== クエリ型別 Recall@10 ===")
    for method, report in rows:
        values = " ".join(f"{t}={report.by_type.get(t, {}).get('recall', 0.0):.3f}"
                          for t in QUERY_TYPES)
        print(f"{method}: {values}")


if __name__ == "__main__":
    main()

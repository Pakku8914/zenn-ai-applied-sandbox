#!/usr/bin/env python3
"""HyDE（仮想文書生成）を実装し、効く型と汚す型を分ける。

    python src/session10/hyde_lab.py

APIキーは不要。`ragkit.llm.StubClient` が決定的な仮想文書を返す。
ここで出る数値は「LLM の実力」ではなく「私たちが置いた仮定」の測定値であることに注意。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from query_lab import (  # noqa: E402
    CountingClient,
    HydeRetriever,
    hyde_document,
    hyde_query,
    make_hyde_client,
)

from ragkit.chunk import chunk_all  # noqa: E402
from ragkit.corpus import load_docs, load_qrels, load_queries  # noqa: E402
from ragkit.eval import evaluate  # noqa: E402
from ragkit.lexical import LexicalIndex  # noqa: E402

TYPES = ("abbrev", "keyword", "multi_condition", "natural", "temporal")
POLLUTED = "通勤交通費"          # 幻覚が持ち込む語
POLLUTED_QUERY_ID = "Q-029"      # 駐車場について聞いているクエリ
REPORT_DIR = Path(__file__).resolve().parents[2] / "reports"


def main() -> None:
    docs, queries, qrels = load_docs(), load_queries(), load_qrels()
    index = LexicalIndex().build(chunk_all(docs, "fixed", size=400, overlap=80))
    client = CountingClient(make_hyde_client())
    by_id = {q.query_id: q for q in queries}

    print("=== 1. 仮想文書のサンプル ===")
    for qid in ("Q-067", POLLUTED_QUERY_ID, "Q-002"):
        q = by_id[qid]
        print(f"[{qid} / {q.type}] {q.text}")
        print(f"  -> {hyde_document(q.text, client)}")

    print("\n=== 2. 検索に投げる文字列（元のクエリを捨てない）===")
    q67 = by_id["Q-067"]
    print(hyde_query(q67.text, hyde_document(q67.text, client)))

    retriever = HydeRetriever(index, client)
    rep_base = evaluate(index, queries, qrels, k=10, label="bm25 / fixed")
    rep_hyde = evaluate(retriever, queries, qrels, k=10, label="bm25 / fixed + HyDE")

    print("\n=== 3. HyDE の効果（Recall@10 / fixed(400/80) / 110クエリ）===")
    print(f"{'type':<18}{'n':>5}{'base':>10}{'hyde':>10}{'diff':>10}")
    for t in TYPES:
        b, a = rep_base.by_type[t], rep_hyde.by_type[t]
        print(f"{t:<18}{int(b['n_queries']):>5}{b['recall']:>10.3f}{a['recall']:>10.3f}"
              f"{a['recall'] - b['recall']:>+10.3f}")
    print(f"{'ALL':<18}{int(rep_base.macro['n_queries']):>5}"
          f"{rep_base.macro['recall']:>10.3f}{rep_hyde.macro['recall']:>10.3f}"
          f"{rep_hyde.macro['recall'] - rep_base.macro['recall']:>+10.3f}")

    print("\n=== 4. 幻覚が検索を汚す（主題のずれ）===")
    q = by_id[POLLUTED_QUERY_ID]
    before = index.search(q.text, k=10)
    after = retriever.search(q.text, k=10)
    n_before = sum(1 for h in before if POLLUTED in h.text)
    n_after = sum(1 for h in after if POLLUTED in h.text)
    print(f"{POLLUTED_QUERY_ID}: {q.text}")
    print(f"  上位10件に「{POLLUTED}」を含むチャンク: {n_before}件 -> {n_after}件")
    print(f"  Recall@10: {rep_base.per_query[q.query_id]['recall']:.3f}"
          f" -> {rep_hyde.per_query[q.query_id]['recall']:.3f}")

    print("\n=== 5. コスト（回数だけを数える）===")
    print(f"LLM 呼び出し: {client.calls} 回 / 入力 {client.input_chars} 文字 "
          f"/ 出力 {client.output_chars} 文字")
    print("  -> レイテンシは測っていない。Stub は即答するので、測っても実運用の待ち時間にならない")

    rep_hyde.to_json(REPORT_DIR / "s10_hyde.json")
    print("\n-> reports/s10_hyde.json")


if __name__ == "__main__":
    main()

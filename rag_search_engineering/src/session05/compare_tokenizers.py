#!/usr/bin/env python3
"""トークナイズ方式（形態素 / 文字bi-gram / 併用）を同じ定規で比べる。

チャンク方式・BM25・判定データをすべて固定し、変える変数はトークナイザだけにする。
morph の行は tools/eval_matrix.py --quick の "bm25 / fixed" と一致するはず。

    python src/session05/compare_tokenizers.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ragkit.chunk import chunk_all  # noqa: E402
from ragkit.corpus import load_docs, load_qrels, load_queries  # noqa: E402
from ragkit.eval import evaluate  # noqa: E402
from ragkit.lexical import LexicalIndex  # noqa: E402

MODES = ("morph", "bigram", "morph+bigram")
TYPES = ("abbrev", "keyword", "multi_condition", "natural", "temporal")
REPORT_DIR = Path(__file__).resolve().parents[2] / "reports"


def main() -> None:
    docs, queries, qrels = load_docs(), load_queries(), load_qrels()
    chunks = chunk_all(docs, "fixed", size=400, overlap=80)

    reports = []
    for mode in MODES:
        index = LexicalIndex(mode=mode).build(chunks)
        rep = evaluate(index, queries, qrels, k=10, label=f"bm25({mode}) / fixed")
        rep.macro["vocab"] = float(len(index.postings))
        rep.macro["total_postings"] = float(sum(len(v) for v in index.postings.values()))
        rep.macro["avgdl"] = index.avgdl
        reports.append(rep)
        print(rep.summary())
        rep.to_json(REPORT_DIR / f"s05_tokenizer_{mode.replace('+', '_')}.json")

    print("\n=== クエリ型別 Recall@10 ===")
    print(f"{'mode':<14}" + "".join(f"{t:>16}" for t in TYPES))
    for mode, rep in zip(MODES, reports):
        print(f"{mode:<14}" + "".join(
            f"{rep.by_type.get(t, {}).get('recall', 0.0):>16.3f}" for t in TYPES))

    print("\n=== 索引の大きさ ===")
    print(f"{'mode':<14}{'語彙数':>10}{'延べポスティング':>18}{'平均文書長':>12}")
    for mode, rep in zip(MODES, reports):
        print(f"{mode:<14}{rep.macro['vocab']:>10.0f}"
              f"{rep.macro['total_postings']:>18.0f}{rep.macro['avgdl']:>12.1f}")


if __name__ == "__main__":
    main()

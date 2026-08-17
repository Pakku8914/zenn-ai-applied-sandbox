#!/usr/bin/env python3
"""実コーパスで転置索引を作り、中身を覗く。

「索引には何が入っているのか」を数字で掴むための道具。
数値は環境ではなくコーパスで決まる（固定シードなので何度実行しても同じ）。

    python src/session05/index_stats.py            # 形態素モード
    python src/session05/index_stats.py --mode bigram
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ragkit.chunk import chunk_all  # noqa: E402
from ragkit.corpus import load_docs  # noqa: E402
from ragkit.lexical import LexicalIndex  # noqa: E402


def summarize(index: LexicalIndex, top: int = 15) -> dict:
    postings = index.postings
    df_list = sorted(((len(v), t) for t, v in postings.items()), reverse=True)
    total_postings = sum(len(v) for v in postings.values())
    hapax = sum(1 for v in postings.values() if len(v) == 1)
    return {
        "n_chunks": len(index.chunks),
        "vocab": len(postings),
        "total_postings": total_postings,
        "avgdl": index.avgdl,
        "hapax": hapax,
        "hapax_ratio": hapax / len(postings) if postings else 0.0,
        "top_df": df_list[:top],
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", default="morph", choices=["morph", "bigram", "morph+bigram"])
    args = ap.parse_args()

    docs = load_docs()
    chunks = chunk_all(docs, "fixed", size=400, overlap=80)
    index = LexicalIndex(mode=args.mode).build(chunks)
    s = summarize(index)

    print(f"mode={args.mode}")
    print(f"チャンク数={s['n_chunks']}")
    print(f"語彙数（辞書のエントリ数）={s['vocab']}")
    print(f"延べポスティング数={s['total_postings']}")
    print(f"平均文書長（語数）={s['avgdl']:.1f}")
    print(f"1文書にしか出ない語={s['hapax']} ({s['hapax_ratio']:.1%})")
    print("df 上位:")
    for df, term in s["top_df"]:
        print(f"  {term} df={df} idf={index._idf(term):.3f}")


if __name__ == "__main__":
    main()

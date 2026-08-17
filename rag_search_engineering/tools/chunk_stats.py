#!/usr/bin/env python3
"""チャンク方式別の統計（チャンク数・長さ・重複率）。セッション4の実測値の出典。"""

from __future__ import annotations

import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ragkit.chunk import chunk_all  # noqa: E402
from ragkit.corpus import load_docs  # noqa: E402

CONFIGS = [
    ("fixed(400/80)", "fixed", dict(size=400, overlap=80)),
    ("fixed(800/160)", "fixed", dict(size=800, overlap=160)),
    ("fixed(200/0)", "fixed", dict(size=200, overlap=0)),
    ("sentence(400)", "sentence", dict(max_chars=400)),
    ("heading(600)", "heading", dict(max_chars=600)),
    ("parent_window(200/600)", "parent_window", dict(child=200, window=600)),
]


def duplication_rate(chunks) -> float:
    """総チャンク文字数 ÷ 元テキスト総文字数。1.0 を超える分が重複。"""
    return sum(len(c.text) for c in chunks)


def main() -> None:
    docs = load_docs()
    base_chars = sum(len(d.full_text) for d in docs)
    print(f"文書数={len(docs)} 元テキスト総文字数={base_chars:,}\n")
    print(f"{'方式':<24}{'チャンク数':>10}{'平均長':>8}{'中央値':>8}{'最大':>7}{'1文書あたり':>12}{'重複率':>8}")
    print("-" * 80)
    for label, method, params in CONFIGS:
        chunks = chunk_all(docs, method, **params)
        lens = [len(c.text) for c in chunks]
        total = duplication_rate(chunks)
        print(f"{label:<24}{len(chunks):>10}{statistics.mean(lens):>8.0f}"
              f"{statistics.median(lens):>8.0f}{max(lens):>7}"
              f"{len(chunks) / len(docs):>12.2f}{total / base_chars:>8.2f}")


if __name__ == "__main__":
    main()

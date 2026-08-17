"""レキシカル検索（転置索引 + BM25）。セッション5の参照実装。

ライブラリに任せず自分で書くのは、スコアの内訳を読めるようにするため。
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict

from .models import Chunk, Hit
from .tokenize_ja import tokenize


class LexicalIndex:
    """転置索引を持ち、BM25 で採点する検索器。

    k1: 語の出現回数の効き方を制御する（大きいほど回数を重視）
    b : 文書長による正規化の強さ（0 で無効・1 で完全に長さで割る）
    """

    def __init__(self, k1: float = 1.2, b: float = 0.75, mode: str = "morph") -> None:
        self.k1 = k1
        self.b = b
        self.mode = mode
        self.postings: dict[str, dict[str, int]] = defaultdict(dict)  # term -> {chunk_id: tf}
        self.doc_len: dict[str, int] = {}
        self.chunks: dict[str, Chunk] = {}
        self.avgdl: float = 0.0

    def build(self, chunks: list[Chunk]) -> "LexicalIndex":
        self.postings.clear()
        self.doc_len.clear()
        self.chunks.clear()
        for c in chunks:
            terms = tokenize(c.text, self.mode)
            self.chunks[c.chunk_id] = c
            self.doc_len[c.chunk_id] = len(terms)
            for term, tf in Counter(terms).items():
                self.postings[term][c.chunk_id] = tf
        self.avgdl = (sum(self.doc_len.values()) / len(self.doc_len)) if self.doc_len else 0.0
        return self

    def _idf(self, term: str) -> float:
        n = len(self.chunks)
        df = len(self.postings.get(term, {}))
        if df == 0:
            return 0.0
        # BM25 の IDF（df が大きい語ほど価値が下がる）
        return math.log(1 + (n - df + 0.5) / (df + 0.5))

    def search(self, query: str, k: int = 10, filters: dict | None = None) -> list[Hit]:
        scores: dict[str, float] = defaultdict(float)
        for term in tokenize(query, self.mode):
            idf = self._idf(term)
            if idf == 0.0:
                continue
            for chunk_id, tf in self.postings[term].items():
                dl = self.doc_len[chunk_id] or 1
                denom = tf + self.k1 * (1 - self.b + self.b * dl / (self.avgdl or 1))
                scores[chunk_id] += idf * (tf * (self.k1 + 1)) / denom

        hits = [
            Hit(cid, self.chunks[cid].doc_id, s, self.chunks[cid].text, self.chunks[cid].meta)
            for cid, s in scores.items()
        ]
        # 検索後にフィルタを掛ける「事後フィルタ」。候補が枯れる問題はセッション7・13の題材
        if filters:
            hits = [h for h in hits if _match(h.meta, filters)]
        hits.sort(key=lambda h: (-h.score, h.chunk_id))
        return hits[:k]


def _match(meta: dict, filters: dict) -> bool:
    for key, want in filters.items():
        got = meta.get(key)
        if isinstance(want, (list, tuple, set)):
            if got not in want:
                return False
        elif got != want:
            return False
    return True

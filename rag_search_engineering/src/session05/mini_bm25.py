#!/usr/bin/env python3
"""転置索引と BM25 の最小実装（セッション5の参照実装）。

  TinyIndex      : 手計算で追える3文書のトイ例（トークナイズ済みの語列を受け取る）
  MyLexicalIndex : 実コーパス用。ragkit.lexical.LexicalIndex と同じ結果を返す

単体で実行すると、手計算で検算できるトイ例のスコアを表示する。

    python src/session05/mini_bm25.py
"""

from __future__ import annotations

import math
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ragkit.models import Chunk, Hit  # noqa: E402
from ragkit.tokenize_ja import tokenize  # noqa: E402

# --- 手計算で追えるトイコーパス（すでにトークナイズ済みとみなす）---------------
TOY: dict[str, list[str]] = {
    "d1": ["有給休暇", "申請", "期限"],
    "d2": ["有給休暇", "有給休暇", "申請", "申請", "期限", "承認", "所属長", "総務部"],
    "d3": ["出張旅費", "精算", "期限"],
}


class TinyIndex:
    """語列を直接受け取る最小の転置索引。BM25 の式だけに集中するための道具。"""

    def __init__(self, docs: dict[str, list[str]]) -> None:
        # 辞書（term） -> ポスティングリスト（{doc_id: tf}）
        self.postings: dict[str, dict[str, int]] = defaultdict(dict)
        self.doc_len: dict[str, int] = {}
        for doc_id, terms in docs.items():
            self.doc_len[doc_id] = len(terms)
            for term, tf in Counter(terms).items():
                self.postings[term][doc_id] = tf
        self.n_docs = len(docs)
        self.avgdl = sum(self.doc_len.values()) / self.n_docs

    def df(self, term: str) -> int:
        """その語を含む文書数。ポスティングリストの長さそのもの。"""
        return len(self.postings.get(term, {}))

    def idf(self, term: str) -> float:
        """BM25 の IDF。df が大きい語（＝ありふれた語）ほど小さくなる。"""
        df = self.df(term)
        if df == 0:
            return 0.0
        return math.log(1 + (self.n_docs - df + 0.5) / (df + 0.5))

    def score(self, query_terms: list[str], k1: float = 1.2, b: float = 0.75) -> dict[str, float]:
        """クエリ語ごとにポスティングリストをたどって加点する（これが検索の本体）。"""
        scores = {doc_id: 0.0 for doc_id in self.doc_len}
        for term in query_terms:
            idf = self.idf(term)
            if idf == 0.0:
                continue  # 索引に無い語は何も起きない（＝略語が効かない理由）
            for doc_id, tf in self.postings[term].items():
                dl = self.doc_len[doc_id]
                denom = tf + k1 * (1 - b + b * dl / self.avgdl)
                scores[doc_id] += idf * (tf * (k1 + 1)) / denom
        return scores


class MyLexicalIndex:
    """実コーパス用の自作 BM25。ragkit.lexical.LexicalIndex と同じ結果を返す。

    ragkit と同じ順序で加算しているため、浮動小数点の丸めまで一致する。
    """

    def __init__(self, k1: float = 1.2, b: float = 0.75, mode: str = "morph") -> None:
        self.k1 = k1
        self.b = b
        self.mode = mode
        self.postings: dict[str, dict[str, int]] = defaultdict(dict)
        self.doc_len: dict[str, int] = {}
        self.chunks: dict[str, Chunk] = {}
        self.avgdl: float = 0.0

    def build(self, chunks: list[Chunk]) -> "MyLexicalIndex":
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
        # 同点は chunk_id で決着させる（実行のたびに順位が変わらないようにする）
        hits.sort(key=lambda h: (-h.score, h.chunk_id))
        return hits[:k]


def format_scores(scores: dict[str, float]) -> str:
    return " ".join(f"{d}={s:.4f}" for d, s in sorted(scores.items()))


def top1(scores: dict[str, float]) -> str:
    return sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]


def main() -> None:
    idx = TinyIndex(TOY)
    print("--- 転置索引 ---")
    print(f"文書数={idx.n_docs}  語彙数={len(idx.postings)}  平均文書長={idx.avgdl:.2f}")
    for term in ("有給休暇", "申請", "期限", "総務部"):
        print(f"  {term}: df={idx.df(term)} idf={idx.idf(term):.4f} "
              f"postings={dict(idx.postings[term])}")

    query = ["有給休暇", "申請"]
    print(f"\n--- クエリ {query} のスコア ---")
    for k1, b in ((1.2, 0.75), (1.2, 0.0), (0.0, 0.75), (3.0, 0.75)):
        scores = idx.score(query, k1=k1, b=b)
        print(f"k1={k1:.1f} b={b:.2f} | {format_scores(scores)} | 1位={top1(scores)}")


if __name__ == "__main__":
    main()

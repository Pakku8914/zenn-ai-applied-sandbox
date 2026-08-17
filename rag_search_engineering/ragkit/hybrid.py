"""ハイブリッド検索（セッション8の参照実装）。

BM25 スコアとコサイン類似度は尺度が違うので足せない。
順位だけを使う RRF と、スコアを正規化して足す方式の2通りを持つ。
"""

from __future__ import annotations

from collections import defaultdict

from .models import Hit


def rrf_fuse(hit_lists: list[list[Hit]], k: int = 10, rrf_k: int = 60) -> list[Hit]:
    """Reciprocal Rank Fusion。順位の逆数を足すのでスコアの尺度差に影響されない。"""
    scores: dict[str, float] = defaultdict(float)
    best: dict[str, Hit] = {}
    for hits in hit_lists:
        for rank, h in enumerate(hits, start=1):
            scores[h.chunk_id] += 1.0 / (rrf_k + rank)
            best.setdefault(h.chunk_id, h)
    fused = [
        Hit(cid, best[cid].doc_id, s, best[cid].text, best[cid].meta) for cid, s in scores.items()
    ]
    fused.sort(key=lambda h: (-h.score, h.chunk_id))
    return fused[:k]


def minmax_fuse(hit_lists: list[list[Hit]], weights: list[float] | None = None, k: int = 10) -> list[Hit]:
    """各リストのスコアを min-max 正規化してから重み付きで足す。

    外れ値1件で分布が潰れる弱点がある（セッション8で RRF と比較する）。
    """
    weights = weights or [1.0] * len(hit_lists)
    if len(weights) != len(hit_lists):
        raise ValueError("weights の数が hit_lists と一致していません")

    scores: dict[str, float] = defaultdict(float)
    best: dict[str, Hit] = {}
    for hits, w in zip(hit_lists, weights):
        if not hits:
            continue
        vals = [h.score for h in hits]
        lo, hi = min(vals), max(vals)
        span = (hi - lo) or 1.0
        for h in hits:
            scores[h.chunk_id] += w * (h.score - lo) / span
            best.setdefault(h.chunk_id, h)
    fused = [
        Hit(cid, best[cid].doc_id, s, best[cid].text, best[cid].meta) for cid, s in scores.items()
    ]
    fused.sort(key=lambda h: (-h.score, h.chunk_id))
    return fused[:k]


class HybridRetriever:
    """2つの検索器を束ねて RRF で統合する検索器。

    candidates: 各検索器から取る候補数（統合前の広さ）。k より大きくする。
    """

    def __init__(self, retrievers: list, candidates: int = 50, mode: str = "rrf",
                 weights: list[float] | None = None) -> None:
        self.retrievers = retrievers
        self.candidates = candidates
        self.mode = mode
        self.weights = weights

    def search(self, query: str, k: int = 10, filters: dict | None = None) -> list[Hit]:
        lists = [r.search(query, k=self.candidates, filters=filters) for r in self.retrievers]
        if self.mode == "rrf":
            return rrf_fuse(lists, k=k)
        if self.mode == "minmax":
            return minmax_fuse(lists, weights=self.weights, k=k)
        raise ValueError(f"unknown mode: {self.mode}")

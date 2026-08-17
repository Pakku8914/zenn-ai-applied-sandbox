#!/usr/bin/env python3
"""セッション8：スコア融合の実装（読者が自分で書く最終形）。

ragkit/hybrid.py の参照実装と1件も違わないことを src/session08/verify.py が確かめる。
融合関数はすべて「Hit のリストのリスト」を受け取り、統合済みの上位k件を返す。
"""

from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path
from statistics import mean, pstdev

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ragkit.models import Hit  # noqa: E402


def _rank(scores: dict[str, float], best: dict[str, Hit], k: int) -> list[Hit]:
    """スコア辞書を Hit の列に戻す。

    同点は chunk_id の昇順で決める。ここを決めないと、辞書の並び順の違いで
    実行のたびに順位が入れ替わり、評価値が再現しなくなる。
    """
    fused = [
        Hit(cid, best[cid].doc_id, s, best[cid].text, best[cid].meta)
        for cid, s in scores.items()
    ]
    fused.sort(key=lambda h: (-h.score, h.chunk_id))
    return fused[:k]


def naive_sum_fuse(hit_lists: list[list[Hit]], k: int = 10) -> list[Hit]:
    """やってはいけない統合：尺度の違うスコアをそのまま足す（比較用）。"""
    scores: dict[str, float] = defaultdict(float)
    best: dict[str, Hit] = {}
    for hits in hit_lists:
        for h in hits:
            scores[h.chunk_id] += h.score
            best.setdefault(h.chunk_id, h)
    return _rank(scores, best, k)


def my_rrf_fuse(hit_lists: list[list[Hit]], k: int = 10, rrf_k: int = 60) -> list[Hit]:
    """RRF（Reciprocal Rank Fusion）。スコアを捨てて順位だけを使う。"""
    scores: dict[str, float] = defaultdict(float)
    best: dict[str, Hit] = {}
    for hits in hit_lists:
        for rank, h in enumerate(hits, start=1):
            scores[h.chunk_id] += 1.0 / (rrf_k + rank)
            best.setdefault(h.chunk_id, h)
    return _rank(scores, best, k)


def my_minmax_fuse(hit_lists: list[list[Hit]], weights: list[float] | None = None,
                   k: int = 10) -> list[Hit]:
    """リストごとに min-max 正規化してから重み付きで足す。"""
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
        span = (hi - lo) or 1.0  # 全件同点なら 0 除算になるので 1 に逃がす
        for h in hits:
            scores[h.chunk_id] += w * (h.score - lo) / span
            best.setdefault(h.chunk_id, h)
    return _rank(scores, best, k)


def zscore_fuse(hit_lists: list[list[Hit]], weights: list[float] | None = None,
                k: int = 10) -> list[Hit]:
    """リストごとに z-score 正規化してから重み付きで足す。

    min-max が「最小と最大」で割るのに対し、こちらは「平均と散らばり」で割る。
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
        mu = mean(vals)
        sd = pstdev(vals) or 1.0  # 1件だけ / 全件同点のときは 0 になる
        for h in hits:
            scores[h.chunk_id] += w * (h.score - mu) / sd
            best.setdefault(h.chunk_id, h)
    return _rank(scores, best, k)


def dedup_by_doc(hits: list[Hit], k: int = 10, per_doc: int = 1) -> list[Hit]:
    """同じ文書から採る件数の上限を per_doc に制限する。

    融合すると同じ文書の複数チャンクが並びやすい。k の単位が
    「チャンク」から「文書」に変わるので、評価の条件も揃えないと比較できない。
    """
    taken: dict[str, int] = defaultdict(int)
    out: list[Hit] = []
    for h in hits:
        if taken[h.doc_id] >= per_doc:
            continue
        taken[h.doc_id] += 1
        out.append(h)
        if len(out) >= k:
            break
    return out


class FusionRetriever:
    """複数の検索器から候補を集め、渡された融合関数で1つの順位にする検索器。

    candidates: 各検索器から取る候補数（統合前の広さ）。
    dedup_docs: True なら文書単位で1件に絞ってから上位k件を返す。
    """

    def __init__(self, retrievers: list, candidates: int = 50, fuse=my_rrf_fuse,
                 dedup_docs: bool = False, **fuse_kwargs) -> None:
        self.retrievers = retrievers
        self.candidates = candidates
        self.fuse = fuse
        self.dedup_docs = dedup_docs
        self.fuse_kwargs = fuse_kwargs

    def search(self, query: str, k: int = 10, filters: dict | None = None) -> list[Hit]:
        lists = [r.search(query, k=self.candidates, filters=filters) for r in self.retrievers]
        if not self.dedup_docs:
            return self.fuse(lists, k=k, **self.fuse_kwargs)
        # 文書単位に絞ると件数が減るので、多めに融合してから絞る
        fused = self.fuse(lists, k=max(k * 5, k), **self.fuse_kwargs)
        return dedup_by_doc(fused, k=k)


class CachedLists:
    """クエリ文 -> 各検索器の候補リスト、をあらかじめ1回だけ作っておく。

    重みを何通りも試すたびに検索し直すと、クエリの埋め込み計算で時間が溶ける。
    候補リストは固定したまま、融合のやり方だけを何度も差し替えるための道具。
    """

    def __init__(self, retrievers: list, queries: list, candidates: int = 50) -> None:
        self.cache = {
            q.text: [r.search(q.text, k=candidates) for r in retrievers] for q in queries
        }

    def retriever(self, fuse, **fuse_kwargs):
        cache = self.cache

        class _Cached:
            def search(self, query: str, k: int = 10, filters: dict | None = None):
                return fuse(cache[query], k=k, **fuse_kwargs)

        return _Cached()


# --- 手で計算できる小さな候補リスト（score_scale.py と verify.py で共有する）-----


def _h(chunk_id: str, score: float) -> Hit:
    return Hit(chunk_id, chunk_id.split("#")[0], score, "", {})


# BM25 のスコアは非有界（0 以上で上限なし）
TOY_LEXICAL = [_h("DOC-0101#001", 18.0), _h("DOC-0207#002", 12.0), _h("DOC-0331#001", 6.0)]
# コサイン類似度は -1 〜 1
TOY_DENSE = [_h("DOC-0450#001", 0.90), _h("DOC-0331#001", 0.86), _h("DOC-0101#001", 0.82)]
# 語がぴたりと一致したチャンクが1件だけ突出したときの BM25 側
TOY_LEXICAL_OUTLIER = [_h("DOC-0999#001", 42.0), *TOY_LEXICAL]

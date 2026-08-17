"""リランク（セッション9の参照実装）。

バイエンコーダ（DenseIndex）はクエリと文書を別々に符号化するため、
両者の相互作用を見られない。クロスエンコーダは1本の入力として一緒に読むので
精度は上がるが、候補数に比例して計算量が増える。
"""

from __future__ import annotations

from .models import Hit

MODEL_NAME = "hotchpotch/japanese-reranker-cross-encoder-xsmall-v1"
MODEL_REVISION = "main"


class CrossEncoderReranker:
    _model = None

    @classmethod
    def get(cls):
        if cls._model is None:
            from sentence_transformers import CrossEncoder

            cls._model = CrossEncoder(MODEL_NAME, revision=MODEL_REVISION)
        return cls._model

    @classmethod
    def rerank(cls, query: str, hits: list[Hit], top_k: int = 10, batch_size: int = 16) -> list[Hit]:
        if not hits:
            return []
        scores = cls.get().predict(
            [(query, h.text) for h in hits], batch_size=batch_size, show_progress_bar=False
        )
        rescored = [
            Hit(h.chunk_id, h.doc_id, float(s), h.text, h.meta) for h, s in zip(hits, scores)
        ]
        rescored.sort(key=lambda h: (-h.score, h.chunk_id))
        return rescored[:top_k]


class RerankRetriever:
    """1段目の検索器の結果をリランクして返す多段検索器。"""

    def __init__(self, base, candidates: int = 50) -> None:
        self.base = base
        self.candidates = candidates

    def search(self, query: str, k: int = 10, filters: dict | None = None) -> list[Hit]:
        hits = self.base.search(query, k=self.candidates, filters=filters)
        return CrossEncoderReranker.rerank(query, hits, top_k=k)

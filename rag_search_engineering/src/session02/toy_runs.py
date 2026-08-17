"""セッション2の演習用データ：10 クエリ × 2 手法の検索結果。

手で計算できる小ささにしてある（検索そのものは行わず、結果だけを再生する）。

判定データ（qrels）は全クエリ共通で、適合文書は 4 件だけとする。

    D1 = grade 2（完全適合） / D2 = grade 2
    D3 = grade 1（部分適合） / D4 = grade 1
    X1・X2・X3 = 不適合（grade 0。qrels には載せない）

手法A は「拾う数は多いが上位が甘い」検索器、手法B は「上位は堅いが取りこぼす」検索器を
模している。手法B の結果が 3 件しかないのは、同じ文書の複数チャンクが上位を占めて
文書単位に畳むと件数が減る、という実際の現象を再現するため（セッション2 本文の第8節）。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ragkit.models import Hit, Query  # noqa: E402

QIDS = [f"T-{i:02d}" for i in range(1, 11)]

RUNS_A: dict[str, list[str]] = {
    "T-01": ["X1", "D3", "D1", "X2", "D4"],
    "T-02": ["D3", "X1", "D1", "D4", "X2"],
    "T-03": ["X1", "X2", "D3", "D1", "D4"],
    "T-04": ["D1", "D3", "X1", "X2", "X3"],
    "T-05": ["X1", "D3", "D4", "X2", "D1"],
    "T-06": ["D3", "D1", "X1", "X2", "D4"],
    "T-07": ["X1", "X2", "D1", "D3", "X3"],
    "T-08": ["D3", "D4", "X1", "D1", "X2"],
    "T-09": ["X1", "D1", "X2", "D3", "D4"],
    "T-10": ["D1", "X1", "D3", "X2", "D4"],
}

RUNS_B: dict[str, list[str]] = {
    "T-01": ["D1", "D2", "X1"],
    "T-02": ["D1", "D3", "X1"],
    "T-03": ["D1", "X1", "D3"],
    "T-04": ["D1", "D2", "D3"],
    "T-05": ["X1", "D1", "X2"],
    "T-06": ["D1", "D3", "D2"],
    "T-07": ["D1", "X1", "X2"],
    "T-08": ["X1", "D1", "D3"],
    "T-09": ["D1", "X1", "D3"],
    "T-10": ["X1", "X2", "D1"],
}

QRELS: dict[str, dict[str, int]] = {
    qid: {"D1": 2, "D2": 2, "D3": 1, "D4": 1} for qid in QIDS
}

# evaluate() に渡すためのクエリ。text にクエリIDをそのまま入れて再生の鍵にする
QUERIES: list[Query] = [Query(query_id=qid, text=qid, type="toy") for qid in QIDS]


def to_hits(doc_ids: list[str]) -> list[Hit]:
    """文書IDの並びを Hit の並びに変換する（スコアは順位の逆数を入れておく）。"""
    return [
        Hit(chunk_id=f"{d}#001", doc_id=d, score=1.0 / (i + 1), text="", meta={})
        for i, d in enumerate(doc_ids)
    ]


class ToyRetriever:
    """記録済みの検索結果を再生するだけの検索器。

    ragkit の Retriever プロトコル（search(query, k, filters) -> list[Hit]）を
    満たすので、evaluate() にそのまま渡せる。
    """

    def __init__(self, runs: dict[str, list[str]], name: str = "toy") -> None:
        self.runs = runs
        self.name = name

    def search(self, query: str, k: int = 10, filters: dict | None = None) -> list[Hit]:
        return to_hits(self.runs[query])[:k]

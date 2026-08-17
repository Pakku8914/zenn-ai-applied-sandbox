"""検索の評価指標（セッション2の参照実装）。

判定データ（qrels）は文書単位、検索結果はチャンク単位なので、
評価の前に「同じ文書の最上位チャンクだけを残す」畳み込みを行う。
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path

from .models import Hit


def hits_to_docs(hits: list[Hit]) -> list[str]:
    """順位を保ったまま doc_id の列に畳む（同一文書の重複を除く）。"""
    seen: set[str] = set()
    out: list[str] = []
    for h in hits:
        if h.doc_id and h.doc_id not in seen:
            seen.add(h.doc_id)
            out.append(h.doc_id)
    return out


def recall_at_k(hits: list[Hit], qrels: dict[str, int], k: int = 10) -> float:
    """適合文書（grade >= 1）のうち上位k件で拾えた割合。"""
    relevant = {d for d, g in qrels.items() if g >= 1}
    if not relevant:
        return 0.0
    got = set(hits_to_docs(hits)[:k])
    return len(relevant & got) / len(relevant)


def precision_at_k(hits: list[Hit], qrels: dict[str, int], k: int = 10) -> float:
    if k <= 0:
        return 0.0
    docs = hits_to_docs(hits)[:k]
    if not docs:
        return 0.0
    return sum(1 for d in docs if qrels.get(d, 0) >= 1) / len(docs)


def mrr(hits: list[Hit], qrels: dict[str, int]) -> float:
    """最初の適合文書の順位の逆数。1件でも上位に出せているかを見る。"""
    for rank, d in enumerate(hits_to_docs(hits), start=1):
        if qrels.get(d, 0) >= 1:
            return 1.0 / rank
    return 0.0


def dcg(gains: list[float]) -> float:
    return sum(g / math.log2(i + 1) for i, g in enumerate(gains, start=1))


def ndcg_at_k(hits: list[Hit], qrels: dict[str, int], k: int = 10) -> float:
    """適合度（0/1/2）を利得として使う。順位の良さを割引付きで評価する。"""
    docs = hits_to_docs(hits)[:k]
    gains = [float(qrels.get(d, 0)) for d in docs]
    ideal = sorted((float(g) for g in qrels.values()), reverse=True)[:k]
    denom = dcg(ideal)
    return (dcg(gains) / denom) if denom else 0.0


@dataclass
class EvalReport:
    label: str
    k: int
    macro: dict[str, float] = field(default_factory=dict)
    per_query: dict[str, dict[str, float]] = field(default_factory=dict)
    by_type: dict[str, dict[str, float]] = field(default_factory=dict)

    def to_json(self, path: str | Path) -> None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(
            json.dumps(
                {"label": self.label, "k": self.k, "macro": self.macro,
                 "by_type": self.by_type, "per_query": self.per_query},
                ensure_ascii=False, indent=2,
            ),
            encoding="utf-8",
        )

    def summary(self) -> str:
        m = self.macro
        return (f"{self.label:<28} Recall@{self.k}={m['recall']:.3f} "
                f"nDCG@{self.k}={m['ndcg']:.3f} MRR={m['mrr']:.3f} "
                f"P@{self.k}={m['precision']:.3f} (n={m['n_queries']:.0f})")


def evaluate(retriever, queries, qrels: dict[str, dict[str, int]], k: int = 10,
             label: str = "", filters: dict | None = None,
             skip_unanswerable: bool = True) -> EvalReport:
    """検索器を全クエリで回して指標を集計する。

    回答不能クエリ（適合文書が存在しない）は既定で除外する。
    含めると Recall が常に 0 になり平均が歪むため（セッション2で扱う）。
    """
    rep = EvalReport(label=label or type(retriever).__name__, k=k)
    per_type: dict[str, list[dict[str, float]]] = {}
    rows: list[dict[str, float]] = []

    for q in queries:
        qr = qrels.get(q.query_id, {})
        if skip_unanswerable and not any(g >= 1 for g in qr.values()):
            continue
        hits = retriever.search(q.text, k=max(k, 10), filters=filters)
        row = {
            "recall": recall_at_k(hits, qr, k),
            "precision": precision_at_k(hits, qr, k),
            "mrr": mrr(hits, qr),
            "ndcg": ndcg_at_k(hits, qr, k),
        }
        rep.per_query[q.query_id] = row
        rows.append(row)
        per_type.setdefault(q.type, []).append(row)

    def avg(items: list[dict[str, float]]) -> dict[str, float]:
        if not items:
            return {"recall": 0.0, "precision": 0.0, "mrr": 0.0, "ndcg": 0.0, "n_queries": 0}
        keys = ("recall", "precision", "mrr", "ndcg")
        out = {key: sum(r[key] for r in items) / len(items) for key in keys}
        out["n_queries"] = float(len(items))
        return out

    rep.macro = avg(rows)
    rep.by_type = {t: avg(v) for t, v in sorted(per_type.items())}
    return rep

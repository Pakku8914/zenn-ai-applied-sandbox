#!/usr/bin/env python3
"""横断復習02（セッション3〜8）の小道具。

この復習章の芯は「良さそうな設定を疑って測る」ことなので、ここに置くのは
新しい検索方式ではなく、**疑うための道具**だけです。

  simple_sum_fuse       尺度の違うスコアをそのまま足す（壊れ方を見る実装・S08）
  SumRetriever          単純加算で統合する検索器（S08）
  meta_match            メタデータの一致判定（S03 のメタデータ設計）
  query_category        そのクエリの適合文書が属するカテゴリ（絞り込み条件の代役）
  filter_run            事前フィルタと事後フィルタを同じ条件で比べる（S07 × S03）
  query_vector/top_ids  クエリの埋め込みと上位k件（S06 × S07）
  ann_recall_sweep      近似検索のリコール。Recall@10 とは別物（S07 × S02）
  load_vectors          既存コレクションからベクトルを取り出す（再計算しない・S07）
  index_seconds         件数から索引作成時間を見積もる（S06 × S04）
  TypeRoutedRetriever   クエリ型ごとに検索器を切り替えるオラクル（S08 × S02）
  subset_mean           per_query から部分集合の平均を出す（S02）
"""

from __future__ import annotations

import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ragkit.eval import recall_at_k  # noqa: E402
from ragkit.models import Hit  # noqa: E402

COLLECTION = "minato_docs_fixed"


def build_indexes(collection: str = COLLECTION):
    """BM25 索引と密ベクトル索引を用意する。

    BM25 は数秒で作れるので毎回作り直す。密ベクトルはセッション6・7で作った
    コレクションを**再利用**する（作り直すと 673件の符号化に約1分かかるため）。
    """
    from ragkit.chunk import chunk_all
    from ragkit.corpus import load_docs
    from ragkit.dense import DenseIndex
    from ragkit.lexical import LexicalIndex

    docs = load_docs()
    chunks = chunk_all(docs, "fixed", size=400, overlap=80)
    lex = LexicalIndex().build(chunks)
    dense = DenseIndex(collection)
    if not dense.client.collection_exists(collection):
        print(f"{collection} が無いので作成します（1分程度・以降は再利用します）")
        dense.build(chunks)
    return docs, chunks, lex, dense

# ---------------------------------------------------------------------------
# 1. スコアの尺度（S05 の BM25 × S06 のコサイン × S08 の統合）
# ---------------------------------------------------------------------------


def simple_sum_fuse(hit_lists: list[list[Hit]], k: int = 10) -> list[Hit]:
    """尺度をそろえずに生スコアを足す。

    BM25 は非有界（このコーパスでは十数〜数十）、コサインは -1〜1。
    足すと大きい方の尺度が勝ち、もう一方は事実上無視される。
    「壊れ方を見るための実装」であって、本番で使ってはいけない。
    """
    scores: dict[str, float] = defaultdict(float)
    best: dict[str, Hit] = {}
    for hits in hit_lists:
        for h in hits:
            scores[h.chunk_id] += h.score
            best.setdefault(h.chunk_id, h)
    fused = [
        Hit(cid, best[cid].doc_id, s, best[cid].text, best[cid].meta) for cid, s in scores.items()
    ]
    # 並べ替えの規則は ragkit.hybrid と同じにそろえる（同点はチャンクID昇順）
    fused.sort(key=lambda h: (-h.score, h.chunk_id))
    return fused[:k]


class SumRetriever:
    """単純加算で統合する検索器（RRF・min-max との比較対象）。"""

    def __init__(self, retrievers: list, candidates: int = 50) -> None:
        self.retrievers = retrievers
        self.candidates = candidates

    def search(self, query: str, k: int = 10, filters: dict | None = None) -> list[Hit]:
        lists = [r.search(query, k=self.candidates, filters=filters) for r in self.retrievers]
        return simple_sum_fuse(lists, k=k)


# ---------------------------------------------------------------------------
# 2. フィルタ（S03 のメタデータ設計 × S07 の絞り込み）
# ---------------------------------------------------------------------------


def meta_match(meta: dict, filters: dict) -> bool:
    """チャンクのメタデータが絞り込み条件に合うか。値のリストは OR として扱う。"""
    for key, want in filters.items():
        got = meta.get(key)
        if isinstance(want, (list, tuple, set)):
            if got not in want:
                return False
        elif got != want:
            return False
    return True


def query_category(query_id: str, qrels: dict, docs_by_id: dict) -> str | None:
    """そのクエリの適合文書が最も多く属するカテゴリ。

    実運用の「カテゴリを指定して検索する」を再現するための条件。
    判定データから作るので、条件の妥当性そのものは議論の対象にしない。
    """
    counts = Counter(
        docs_by_id[d].category
        for d, g in qrels.get(query_id, {}).items()
        if g >= 1 and d in docs_by_id
    )
    return counts.most_common(1)[0][0] if counts else None


def filter_run(retriever, queries, qrels, docs_by_id, k: int = 10,
               post: bool = False) -> dict[str, float]:
    """カテゴリで絞ったときの返却件数・ゼロヒット数・Recall@k を集計する。

    post=False : 検索器にフィルタを渡す（絞ってから上位k件を埋める）
    post=True  : 上位k件を取ってから絞る（＝候補が枯れる実装）

    判定データも同じカテゴリに絞ってから測る。絞り込み後の世界で
    「取れるはずのものが取れているか」を見たいため。
    """
    n_hits: list[int] = []
    recalls: list[float] = []
    for q in queries:
        qr = qrels.get(q.query_id, {})
        if not any(g >= 1 for g in qr.values()):
            continue  # 回答不能クエリは ragkit.eval.evaluate と同じく除く
        cat = query_category(q.query_id, qrels, docs_by_id)
        if cat is None:
            continue
        filters = {"category": cat}
        if post:
            hits = [h for h in retriever.search(q.text, k=k) if meta_match(h.meta, filters)]
        else:
            hits = retriever.search(q.text, k=k, filters=filters)
        qr_cat = {
            d: g for d, g in qr.items()
            if d in docs_by_id and docs_by_id[d].category == cat
        }
        n_hits.append(len(hits))
        recalls.append(recall_at_k(hits, qr_cat, k))
    n = len(n_hits) or 1
    return {
        "n_queries": float(len(n_hits)),
        "mean_hits": sum(n_hits) / n,
        "zero_hits": float(sum(1 for c in n_hits if c == 0)),
        "recall": sum(recalls) / n,
    }


# ---------------------------------------------------------------------------
# 3. 近似検索のリコール（S07）
# ---------------------------------------------------------------------------


def query_vector(text: str) -> list[float]:
    """クエリ側の埋め込み（"query: " prefix は Embedder が付ける・S06）。"""
    from ragkit.dense import Embedder

    return Embedder.encode_query(text).tolist()


def top_ids(index, vec: list[float], k: int = 10, ef: int | None = None,
            exact: bool = False) -> list[str]:
    """上位k件のチャンクIDを返す。exact=True で総当たり、ef で近似の探索幅を指定する。"""
    from qdrant_client.models import SearchParams

    res = index.client.query_points(
        index.collection,
        query=vec,
        limit=k,
        search_params=SearchParams(hnsw_ef=ef, exact=exact),
        with_payload=True,
    )
    return [(p.payload or {}).get("chunk_id", str(p.id)) for p in res.points]


def ann_recall_sweep(index, queries, k: int = 10,
                     efs: tuple[int, ...] = (4, 8, 16, 32, 64, 128)) -> dict[int, float]:
    """`ef` を振って近似検索のリコールを測る。

    ここでいうリコールは「総当たりの上位k件をどれだけ再現できたか」であり、
    判定データは一切使わない。検索の Recall@k（適合文書を拾えた割合）とは別物。
    呼び分けを崩すと、ANN の設定ミスと検索精度の劣化が区別できなくなる。
    """
    vecs = [query_vector(q.text) for q in queries]
    exact_sets = [set(top_ids(index, v, k=k, exact=True)) for v in vecs]
    out: dict[int, float] = {}
    for ef in efs:
        hit = tot = 0
        for v, ex in zip(vecs, exact_sets):
            hit += len(ex & set(top_ids(index, v, k=k, ef=ef)))
            tot += len(ex)
        out[ef] = hit / tot if tot else 0.0
    return out


class EfIndex:
    """`ef` を固定して検索する薄いラッパ（ragkit.eval.evaluate に渡すため）。

    DenseIndex.search は ef を受け取れるが、evaluate は ef を渡さない。
    設定を評価に載せたいときは、このように「設定を持った検索器」に包む。
    """

    def __init__(self, index, ef: int) -> None:
        self.index = index
        self.ef = ef

    def search(self, query: str, k: int = 10, filters: dict | None = None) -> list[Hit]:
        return self.index.search(query, k=k, filters=filters, ef=self.ef)


def load_vectors(index, limit: int = 4000):
    """既存コレクションからベクトルとチャンクIDを取り出す（埋め込みを作り直さない）。"""
    import numpy as np

    points, _ = index.client.scroll(
        index.collection, limit=limit, with_payload=True, with_vectors=True
    )
    ids: list[str] = []
    vecs: list[list[float]] = []
    for p in points:
        vec = p.vector
        if isinstance(vec, dict):  # 名前付きベクトルの場合
            vec = next(iter(vec.values()))
        ids.append((p.payload or {}).get("chunk_id", str(p.id)))
        vecs.append(list(vec))
    return ids, np.asarray(vecs, dtype="float32")


# ---------------------------------------------------------------------------
# 4. 索引作成の見積もり（S06 × S04）
# ---------------------------------------------------------------------------


def index_seconds(n_chunks: int, ms_per_chunk: float = 56.8) -> float:
    """件数あたりのスループットから索引作成時間（秒）を見積もる。

    引数に単位を明示しているのは、見積もりで最初に壊れるのが「単位の取り違え」だから。
    この関数が答えるのは「同じ長さのチャンクを n 件」という前提の下での時間だけ。
    """
    return n_chunks * ms_per_chunk / 1000.0


# ---------------------------------------------------------------------------
# 5. クエリ型ごとのルーティング（S02 × S08）
# ---------------------------------------------------------------------------


class TypeRoutedRetriever:
    """クエリ型ごとに検索器を切り替える。**型が既知である前提のオラクル**。

    実運用ではクエリに型ラベルは付いてこない。この検索器で測れるのは
    「型の判定が完璧だったときの上限」であって、そのまま出せる性能ではない。
    その事実をコードで見えるようにするため、型は判定データ由来の辞書から引く。
    """

    def __init__(self, routes: dict[str, object], default, type_of: dict[str, str]) -> None:
        self.routes = routes
        self.default = default
        self.type_of = type_of

    def search(self, query: str, k: int = 10, filters: dict | None = None) -> list[Hit]:
        retriever = self.routes.get(self.type_of.get(query, ""), self.default)
        return retriever.search(query, k=k, filters=filters)


def subset_mean(rep, query_ids, metric: str = "recall") -> float:
    """評価レポートの per_query から、指定したクエリ集合だけの平均を出す。

    条件を測り直さずに部分集合の数字が作れるので、
    「学習用と検証用に分けて比べる」が検索を1回も追加せずにできる。
    """
    vals = [rep.per_query[qid][metric] for qid in query_ids if qid in rep.per_query]
    return sum(vals) / len(vals) if vals else 0.0

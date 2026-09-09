#!/usr/bin/env python3
"""セッション5: 同じコーパスを4通りの方式で検索して、上位3件の並びを比べる。

OpenSearch を使う唯一の章です。既定の4サービスには含まれないので、先に起動します。

    docker compose --profile search up -d opensearch
    docker compose exec app python src/session05/hybrid_lab.py

比べるのは次の4通りです。

    1. ベクトルのみ（k-NN）        … 意味は近いが、上位のスコア差が小さい
    2. BM25 のみ                  … 語が一致すればスコアが大きく開く
    3. ハイブリッド（0.7 : 0.3）  … 正規化してから重み付きで合成する
    4. ハイブリッド ＋ リランク    … クエリと候補を組で評価し直して並べ替える
"""

from __future__ import annotations

import os
import sys
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, "/workspace")
sys.path.insert(0, "/workspace/src/session04")
sys.path.insert(0, "/workspace/src/session05")

from opensearchpy import OpenSearch  # noqa: E402

from awskit import clients  # noqa: E402

import chunking  # noqa: E402
import retriever  # noqa: E402
import vector_store  # noqa: E402

OPENSEARCH_URL = os.environ.get("OPENSEARCH_URL", "http://opensearch:9200")
_PARSED = urllib.parse.urlparse(OPENSEARCH_URL)
OPENSEARCH_HOST = _PARSED.hostname or "opensearch"
OPENSEARCH_PORT = _PARSED.port or 9200

INDEX = "sample-shoji-docs"

# キーワード側を効かせるため、語を半角スペースで区切ったクエリを使う
QUERY = "有給休暇 繰越 上限"

VECTOR_WEIGHT = 0.7  # Knowledge Bases の HYBRID（本教材のモック）と同じ重み配分


def reachable(timeout: float = 25.0) -> bool:
    """OpenSearch が使える状態かを確かめる（起動直後の準備待ちも兼ねる）。"""
    url = f"{OPENSEARCH_URL}/_cluster/health?wait_for_status=yellow&timeout=20s"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as res:
            return res.status == 200
    except (urllib.error.URLError, OSError, TimeoutError):
        return False


def client() -> OpenSearch:
    """opensearch-py 3.x のクライアント。引数は必ずキーワード指定で渡す。"""
    return OpenSearch(
        hosts=[{"host": OPENSEARCH_HOST, "port": OPENSEARCH_PORT}], use_ssl=False
    )


def build_index(os_client: OpenSearch, runtime, documents: list[dict]) -> int:
    """索引を作り直して12文書を投入する（1文書=1チャンク）。

    `knn: True` を設定した索引でだけ `knn_vector` 列が使えます。`space_type` を
    `cosinesimil` にすると、スコアは `(1 + コサイン類似度) / 2` として返ります
    （0〜1に収まるので、そのまま順位比較に使えます）。
    """
    # opensearch-py 3.x は index= のキーワード指定が必須（位置引数だと TypeError）
    if os_client.indices.exists(index=INDEX):
        os_client.indices.delete(index=INDEX)

    os_client.indices.create(
        index=INDEX,
        body={
            "settings": {
                "index": {"knn": True, "number_of_shards": 1, "number_of_replicas": 0}
            },
            "mappings": {
                "properties": {
                    "content": {"type": "text"},
                    "category": {"type": "keyword"},
                    "embedding": {
                        "type": "knn_vector",
                        "dimension": 1024,
                        "method": {
                            "name": "hnsw",
                            "space_type": "cosinesimil",
                            "engine": "lucene",
                        },
                    },
                }
            },
        },
    )

    for doc in documents:
        vector = vector_store.embed_text(runtime, doc["text"])
        os_client.index(
            index=INDEX,
            id=doc["id"],
            body={
                "content": doc["text"],
                "category": doc["category"],
                "embedding": vector,
            },
            refresh=True,
        )
    return int(os_client.count(index=INDEX)["count"])


def _hits(response: dict) -> list[dict]:
    return [
        {"doc_id": hit["_id"], "score": float(hit["_score"]), "text": hit["_source"]["content"]}
        for hit in response["hits"]["hits"]
    ]


def knn_search(os_client: OpenSearch, vector: list[float], *, top_k: int = 3) -> list[dict]:
    """ベクトルのみ（意味の近さ）で引く。"""
    return _hits(
        os_client.search(
            index=INDEX,
            body={"size": top_k, "query": {"knn": {"embedding": {"vector": vector, "k": top_k}}}},
        )
    )


def bm25_search(os_client: OpenSearch, query: str, *, top_k: int = 3) -> list[dict]:
    """キーワードのみ（BM25）で引く。"""
    return _hits(
        os_client.search(
            index=INDEX, body={"size": top_k, "query": {"match": {"content": query}}}
        )
    )


def minmax(scores: dict[str, float]) -> dict[str, float]:
    """スコアを 0〜1 に正規化する。

    **ここが合成の要点です。** k-NN のスコアは上位間の差が小さく、BM25 は大きく開きます。
    尺度が違うものをそのまま足すと、必ず BM25 側が支配します。正規化してから
    重みを掛けることで、「どちらをどれだけ信じるか」を重みだけで表せます。
    """
    if not scores:
        return {}
    hi, lo = max(scores.values()), min(scores.values())
    if hi == lo:
        return {key: 1.0 for key in scores}
    return {key: (value - lo) / (hi - lo) for key, value in scores.items()}


def hybrid_search(
    os_client: OpenSearch,
    runtime,
    query: str,
    *,
    top_k: int = 3,
    candidate_k: int = 10,
    vector_weight: float = VECTOR_WEIGHT,
) -> list[dict]:
    """ベクトルと BM25 をそれぞれ広めに取り、正規化して重み付きで合成する。"""
    vector = vector_store.embed_text(runtime, query)
    knn = knn_search(os_client, vector, top_k=candidate_k)
    bm25 = bm25_search(os_client, query, top_k=candidate_k)

    knn_norm = minmax({h["doc_id"]: h["score"] for h in knn})
    bm25_norm = minmax({h["doc_id"]: h["score"] for h in bm25})

    merged: dict[str, dict] = {h["doc_id"]: h for h in bm25}
    merged.update({h["doc_id"]: h for h in knn})

    fused = [
        {
            "doc_id": doc_id,
            "text": hit["text"],
            # 片方に出てこなかった文書は、その方式では0点として扱う
            "score": round(
                vector_weight * knn_norm.get(doc_id, 0.0)
                + (1 - vector_weight) * bm25_norm.get(doc_id, 0.0),
                6,
            ),
        }
        for doc_id, hit in merged.items()
    ]
    # 同点のときの並びを固定する（判定を再現可能にするため）
    fused.sort(key=lambda h: (-h["score"], h["doc_id"]))
    return fused[:top_k]


def rerank_hits(agent, query: str, hits: list[dict], *, top_n: int = 3) -> list[dict]:
    """ハイブリッドの候補を `Rerank` API で並べ直す。"""
    reordered = retriever.rerank(
        agent, query, [{"text": h["text"]} for h in hits], top_n=top_n
    )
    return [
        {
            "doc_id": hits[entry["source_index"]]["doc_id"],
            "text": entry["text"],
            "score": entry["rerank_score"],
        }
        for entry in reordered
    ]


def top_ids(hits: list[dict], *, top_k: int = 3) -> list[str]:
    return [h["doc_id"] for h in hits[:top_k]]


def main() -> int:
    if not reachable():
        print("SKIP: OpenSearch が起動していません（docker compose --profile search up -d opensearch）")
        return 0

    runtime = clients.bedrock_runtime()
    agent = clients.agent_runtime()
    documents = chunking.load_documents()
    os_client = client()

    count = build_index(os_client, runtime, documents)
    print("=== 4通りの検索を同じコーパスで比べる ===")
    print(f"索引: {INDEX} / 件数: {count} / クエリ: {QUERY}")
    print()

    vector = vector_store.embed_text(runtime, QUERY)
    knn = knn_search(os_client, vector, top_k=3)
    bm25 = bm25_search(os_client, QUERY, top_k=3)
    # リランクは「広く取ってから絞る」ため、合成結果を5件まで取ってから3件に詰める
    candidates = hybrid_search(os_client, runtime, QUERY, top_k=5)
    hybrid = candidates[:3]
    reranked = rerank_hits(agent, QUERY, candidates, top_n=3)

    print("方式 | 1位 | 2位 | 3位")
    for label, hits in (
        ("ベクトルのみ(k-NN)", knn),
        ("BM25のみ", bm25),
        ("ハイブリッド(0.7:0.3)", hybrid),
        ("ハイブリッド+リランク", reranked),
    ):
        ids = top_ids(hits)
        print(f"{label} | " + " | ".join(ids))
    print()

    print("--- スコアの尺度の違い（正規化が必要な理由） ---")
    print(f"k-NN  1位 {knn[0]['doc_id']} {knn[0]['score']:.4f} / 2位 {knn[1]['doc_id']} {knn[1]['score']:.4f}")
    print(f"BM25  1位 {bm25[0]['doc_id']} {bm25[0]['score']:.4f} / 2位 {bm25[1]['doc_id']} {bm25[1]['score']:.4f}")
    print(f"k-NN の1位と2位の差: {knn[0]['score'] - knn[1]['score']:.4f}")
    print(f"BM25 の1位と2位の差: {bm25[0]['score'] - bm25[1]['score']:.4f}")
    print()

    print("--- 並びが方式で変わったか ---")
    print(f"k-NN と BM25 の上位3件が同じ並び: {'はい' if top_ids(knn) == top_ids(bm25) else 'いいえ'}")
    print(f"k-NN とハイブリッドが同じ並び: {'はい' if top_ids(knn) == top_ids(hybrid) else 'いいえ'}")
    print(f"ハイブリッドとリランク後が同じ並び: {'はい' if top_ids(hybrid) == top_ids(reranked) else 'いいえ'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

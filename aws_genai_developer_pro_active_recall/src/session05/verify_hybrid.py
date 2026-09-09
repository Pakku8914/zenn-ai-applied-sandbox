#!/usr/bin/env python3
"""セッション5の検証（OpenSearch を使う部分）。

ベクトルのみ・BM25 のみ・ハイブリッド・ハイブリッド＋リランクの4通りを同じコーパスで
実行し、**並びが方式で変わること**と、**スコアの尺度が方式で違うこと**を確かめます。

OpenSearch は既定の4サービスに含まれないため、起動していなければ SKIP（終了コード0）で
抜けます。CI などで必ず実行させたい場合は `REQUIRE_OPENSEARCH=1` を設定してください。

    docker compose --profile search up -d opensearch
    docker compose exec app python src/session05/verify_hybrid.py
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request

sys.path.insert(0, "/workspace")
sys.path.insert(0, "/workspace/src/session04")
sys.path.insert(0, "/workspace/src/session05")

from awskit import clients  # noqa: E402

import chunking  # noqa: E402
import hybrid_lab  # noqa: E402
import vector_store  # noqa: E402

FAILURES: list[str] = []

QUERY = hybrid_lab.QUERY  # "有給休暇 繰越 上限"


def check(label: str, condition: bool, detail: object = "") -> None:
    if condition:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label} {detail}")
        FAILURES.append(label)


def mock_post(path: str, payload: dict) -> dict:
    req = urllib.request.Request(
        f"{clients.mock_base_url()}{path}",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as res:
        return json.loads(res.read())


def section(title: str) -> None:
    print(f"\n=== {title} ===")


def main() -> int:
    if not hybrid_lab.reachable():
        print("SKIP: OpenSearch が起動していません（docker compose --profile search up -d opensearch）")
        if os.environ.get("REQUIRE_OPENSEARCH") == "1":
            print("REQUIRE_OPENSEARCH=1 が設定されているため、これを失敗として扱います")
            return 1
        return 0

    mock_post("/_mock/reset", {})

    runtime = clients.bedrock_runtime()
    agent = clients.agent_runtime()
    documents = chunking.load_documents()
    os_client = hybrid_lab.client()

    section("1. 索引の準備")
    count = hybrid_lab.build_index(os_client, runtime, documents)
    check("knn を有効にした索引に12件投入できる", count == 12, count)
    check("索引が存在する（index= のキーワード指定が必須）",
          os_client.indices.exists(index=hybrid_lab.INDEX))
    raised = False
    try:
        hybrid_lab.knn_search(
            os_client, vector_store.embed_text(runtime, QUERY, dimensions=512), top_k=3
        )
    except Exception:
        raised = True
    check("512次元のベクトルでは k-NN 検索がエラーになる（索引の次元と一致が必要）", raised)

    section("2. ベクトルのみ（k-NN）と BM25 のみ")
    vector = vector_store.embed_text(runtime, QUERY)
    knn = hybrid_lab.knn_search(os_client, vector, top_k=3)
    bm25 = hybrid_lab.bm25_search(os_client, QUERY, top_k=3)
    check("k-NN の1位は hr-001", knn[0]["doc_id"] == "hr-001", hybrid_lab.top_ids(knn))
    check("k-NN の2位は sec-003", knn[1]["doc_id"] == "sec-003", hybrid_lab.top_ids(knn))
    check("BM25 の1位は hr-001", bm25[0]["doc_id"] == "hr-001", hybrid_lab.top_ids(bm25))
    check("BM25 の2位は sec-001", bm25[1]["doc_id"] == "sec-001", hybrid_lab.top_ids(bm25))
    check("k-NN と BM25 で上位3件の並びが違う",
          hybrid_lab.top_ids(knn) != hybrid_lab.top_ids(bm25),
          (hybrid_lab.top_ids(knn), hybrid_lab.top_ids(bm25)))

    knn_gap = knn[0]["score"] - knn[1]["score"]
    bm25_gap = bm25[0]["score"] - bm25[1]["score"]
    check("k-NN は上位間のスコア差が小さく、BM25 は大きく開く（尺度が違う）",
          knn_gap < bm25_gap, (knn_gap, bm25_gap))

    section("3. 正規化してから合成する（ハイブリッド）")
    knn_norm = hybrid_lab.minmax({h["doc_id"]: h["score"] for h in knn})
    bm25_norm = hybrid_lab.minmax({h["doc_id"]: h["score"] for h in bm25})
    check("正規化すると各方式の1位が 1.0 になる",
          abs(knn_norm["hr-001"] - 1.0) < 1e-9 and abs(bm25_norm["hr-001"] - 1.0) < 1e-9,
          (knn_norm["hr-001"], bm25_norm["hr-001"]))
    candidates = hybrid_lab.hybrid_search(os_client, runtime, QUERY, top_k=5)
    hybrid = candidates[:3]
    check("ハイブリッドの1位は hr-001", hybrid[0]["doc_id"] == "hr-001", hybrid_lab.top_ids(hybrid))
    check("両方式で1位の文書は合成スコアが 1.0（満点）になる",
          abs(hybrid[0]["score"] - 1.0) < 1e-6, hybrid[0]["score"])
    check("合成スコアが降順に並んでいる",
          [h["score"] for h in hybrid] == sorted((h["score"] for h in hybrid), reverse=True),
          [h["score"] for h in hybrid])

    section("4. ハイブリッド ＋ リランク")
    reranked = hybrid_lab.rerank_hits(agent, QUERY, candidates, top_n=3)
    check("リランク後も1位は hr-001", reranked[0]["doc_id"] == "hr-001", hybrid_lab.top_ids(reranked))
    check("リランク後の1位と2位のスコア差が 0.1 より大きい",
          reranked[0]["score"] - reranked[1]["score"] > 0.1,
          [h["score"] for h in reranked])
    check("リランクは上位3件だけを返す", len(reranked) == 3, len(reranked))

    section("5. 4通りの並びを比べる")
    orders = {
        "ベクトルのみ": hybrid_lab.top_ids(knn),
        "BM25のみ": hybrid_lab.top_ids(bm25),
        "ハイブリッド": hybrid_lab.top_ids(hybrid),
        "ハイブリッド+リランク": hybrid_lab.top_ids(reranked),
    }
    for label, order in orders.items():
        print(f"  --   {label}: {order}")
    check("4通りの上位3件がすべて同じ並びにはならない",
          len({tuple(order) for order in orders.values()}) > 1, orders)
    check("どの方式でも1位は hr-001（正解文書は方式に依存しない）",
          {order[0] for order in orders.values()} == {"hr-001"}, orders)

    print()
    if FAILURES:
        print(f"NG: {len(FAILURES)} 件の検証に失敗しました -> {FAILURES}")
        return 1
    print("セッション5（ハイブリッド検索）の検証に成功しました（課金は一切発生していません）")
    return 0


if __name__ == "__main__":
    sys.exit(main())

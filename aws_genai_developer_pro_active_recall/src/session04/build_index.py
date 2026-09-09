#!/usr/bin/env python3
"""セッション4: ベクトルストアを構築し、メタデータフィルタの効き方を観察する。

    docker compose exec app python src/session04/build_index.py --reset   # 空から作る
    docker compose exec app python src/session04/build_index.py           # 2回目（増分更新）
"""

from __future__ import annotations

import json
import sys
import urllib.request

sys.path.insert(0, "/workspace")
sys.path.insert(0, "/workspace/src/session04")

from awskit import clients  # noqa: E402

import vector_store  # noqa: E402

QUERY = "有給休暇の繰越上限"

# 出力順を固定するため、カテゴリは明示的に列挙する
CATEGORIES = ["IT", "経費", "人事", "セキュリティ"]

# 「同じ質問に対して母集団だけを変える」ための条件一覧
CONDITIONS: list[tuple[str, dict]] = [
    ("フィルタなし", {}),
    ("カテゴリ=人事", {"category": "人事"}),
    ("カテゴリ=IT", {"category": "IT"}),
    ("更新日>=2026-06-01", {"updated_from": "2026-06-01"}),
    (
        "カテゴリ=人事 かつ 更新日>=2026-06-01",
        {"category": "人事", "updated_from": "2026-06-01"},
    ),
]


def mock_calls() -> int:
    """モック専用の会計 API から呼び出し回数を読む。

    実 AWS では CloudWatch の `Invocations` メトリクスに相当します。
    ここでは「埋め込みを何回作り直したか」を見るためだけに使います。
    """
    with urllib.request.urlopen(
        f"{clients.mock_base_url()}/_mock/usage", timeout=10
    ) as res:
        return int(json.loads(res.read())["calls"])


def rank_of(results: list[dict], doc_id: str) -> str:
    for position, row in enumerate(results, start=1):
        if row["doc_id"] == doc_id:
            return str(position)
    return "圏外"


def main() -> int:
    reset = "--reset" in sys.argv
    runtime = clients.bedrock_runtime()
    agent = clients.agent_runtime()
    chunks = vector_store.load_chunks()

    print("=== サンプル商事 ベクトルストアの構築 ===")
    print(
        f"埋め込みモデル: {vector_store.EMBED_MODEL_ID}"
        f"（{vector_store.EMBED_DIMENSIONS} 次元・L2正規化済み）"
    )
    print(f"取り込み対象: {len(chunks)} チャンク（1文書=1チャンク）")

    with vector_store.connect() as conn:
        if reset:
            with conn.cursor() as cur:
                cur.execute("TRUNCATE doc_chunks")
            conn.commit()

        print("\n--- 1. 同期（増分更新方式） ---")
        before = mock_calls()
        stats = vector_store.sync(conn, runtime, chunks)
        print(
            f"新規: {stats['inserted']} / 更新: {stats['updated']} / "
            f"変更なし: {stats['skipped']} / 削除: {stats['deleted']}"
        )
        print(f"埋め込みの呼び出し: {mock_calls() - before} 回")

        print("\n--- 2. 器の状態 ---")
        with conn.cursor() as cur:
            # 検索時に探索する近傍の広さ。大きくすると精度が上がり遅くなる
            cur.execute("SET hnsw.ef_search = 100")
            cur.execute(
                "SELECT count(*), max(vector_dims(embedding)) FROM doc_chunks"
            )
            rows, dims = cur.fetchone()
            cur.execute(
                "SELECT indexname, indexdef FROM pg_indexes "
                "WHERE tablename = 'doc_chunks' ORDER BY indexname"
            )
            indexes = cur.fetchall()
            cur.execute("SHOW hnsw.ef_search")
            ef_search = cur.fetchone()[0]
        print(f"行数: {rows} / ベクトルの次元: {dims}")
        print(
            "HNSW 索引: "
            + ", ".join(name for name, define in indexes if "USING hnsw" in define)
        )
        print(
            "メタデータ索引: "
            + " / ".join(name for name, _ in indexes if name.endswith("_idx"))
        )
        print(f"hnsw.ef_search: {ef_search}")
        counts = vector_store.category_counts(conn, CATEGORIES)
        print("カテゴリ別: " + " / ".join(f"{k}={v}" for k, v in counts.items()))

        print("\n--- 3. メタデータフィルタが選ぶ母集団 ---")
        for label, condition in CONDITIONS:
            ids = vector_store.candidates(conn, **condition)
            print(f"{label}: {len(ids)} 件（{', '.join(ids)}）")

        print(f"\n--- 4. コサイン距離検索: 「{QUERY}」 ---")
        baseline: list[dict] = []
        for label, condition in CONDITIONS:
            results = vector_store.search(conn, runtime, QUERY, top_k=3, **condition)
            if not condition:
                baseline = results
            print(f"{label}: hr-001 の順位 = {rank_of(results, 'hr-001')}")
        top = baseline[0]
        print(
            f"1位（フィルタなし）: {top['doc_id']} / {top['title']} / "
            f"{top['category']} / {top['updated_at']}"
        )
        print(f"出典: {top['source_uri']}")

        print("\n--- 5. マネージド側（Knowledge Bases の Retrieve）との対照 ---")
        managed = agent.retrieve(
            knowledgeBaseId="SAMPLEKB01",
            retrievalQuery={"text": QUERY},
            retrievalConfiguration={"vectorSearchConfiguration": {"numberOfResults": 3}},
        )["retrievalResults"]
        print(f"自前 pgvector の1位: {top['doc_id']} / {top['title']}")
        print(
            f"Knowledge Bases の1位: {managed[0]['metadata']['title']} / "
            f"{managed[0]['location']['s3Location']['uri']}"
        )
        print("同じ質問で同じ文書が1位です。違うのは「索引を誰が作り、鮮度を誰が保つか」です。")

    return 0


if __name__ == "__main__":
    sys.exit(main())

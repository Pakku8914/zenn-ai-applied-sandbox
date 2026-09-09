#!/usr/bin/env python3
"""セッション17: 検索側の速さと、ベクトルストアの運用監視。

    docker compose exec app python src/session17/retrieval_perf.py

検索は「基盤モデルを呼ぶ前」の工程なので、ここが遅いとストリーミングでも隠せません
（最初の差分は検索が終わるまで作れない）。本章で見るのは3点です。

    1. 索引が本当に使われているか   → **EXPLAIN の実行計画**で確かめる
    2. 母集団を先に絞れているか     → メタデータフィルタで候補を減らす
    3. 索引が劣化していないか       → 定点クエリの1位が変わっていないかを見張る

**速さの判定に実行時間を使いません。** 行数が少ないと素の走査のほうが安いと
見積もられることがあり、時間は環境で変わります。判定は「Index Scan か Seq Scan か」
という**計画の違い**で行います。

索引の作り方（HNSW・`vector_cosine_ops`）はセッション4、チャンクと検索方式の
設計はセッション5で扱いました。本章は**運用として何を見張るか**だけを足します。
"""

from __future__ import annotations

import sys

sys.path.insert(0, "/workspace")
sys.path.insert(0, "/workspace/src/session04")

from awskit import clients  # noqa: E402

import vector_store  # noqa: E402  セッション4（埋め込み・投入・検索）

TOP_K = 3

# 監視用の定点クエリ。1位が変わったら索引かデータを疑う（期待値は実測で固定）
GOLDEN_QUERY = "有給休暇の繰越上限"
GOLDEN_TOP1 = "hr-001"

HNSW_INDEX = "doc_chunks_embedding_hnsw"
META_INDEXES = ("doc_chunks_category_idx", "doc_chunks_updated_at_idx")

CATEGORIES = ("IT", "経費", "人事", "セキュリティ")

# 索引が効く並び方（`<=>` はコサイン距離。セッション4と同じ演算子）
SEARCH_SQL = """
    SELECT doc_id
    FROM doc_chunks
    ORDER BY embedding <=> %s::vector
    LIMIT %s
"""


# ---------------------------------------------------------------------------
# 母集団を固定する
# ---------------------------------------------------------------------------


def baseline(conn, runtime) -> dict:
    """セッション4の状態（1文書=1チャンク・12行）に戻す。

    セッション5でチャンク分割の実験をしていると、同じ文書が複数行に増えています。
    索引の効き方を比べるには**母集団を固定**しなければならないので、
    比較の前にここで揃えます（セッション5の演習をもう一度回せば元に戻ります）。
    """
    with conn.cursor() as cur:
        cur.execute("DELETE FROM doc_chunks WHERE chunk_index > 0")
    conn.commit()
    vector_store.sync(conn, runtime, vector_store.load_chunks())
    return health(conn)


def health(conn) -> dict:
    """ベクトルストアの健康診断。**性能の前にデータ品質を見る。**

    埋め込みが入っていない行・同じ文書の重複行・次元の不一致は、
    「検索が当たらない」の原因として最初に疑うべきものです。
    どれもクエリ1本で数えられます。
    """
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM doc_chunks")
        rows = int(cur.fetchone()[0])
        cur.execute("SELECT max(vector_dims(embedding)) FROM doc_chunks")
        dims = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM doc_chunks WHERE embedding IS NULL")
        missing = int(cur.fetchone()[0])
        cur.execute(
            "SELECT count(*) FROM ("
            " SELECT doc_id FROM doc_chunks GROUP BY doc_id HAVING count(*) > 1"
            ") AS duplicated"
        )
        duplicated = int(cur.fetchone()[0])
        cur.execute("SELECT count(DISTINCT category) FROM doc_chunks")
        categories = int(cur.fetchone()[0])
        cur.execute(
            "SELECT indexname, indexdef FROM pg_indexes WHERE tablename = 'doc_chunks'"
        )
        indexes = {name: definition for name, definition in cur.fetchall()}
    conn.commit()
    return {
        "rows": rows,
        "dims": int(dims) if dims is not None else 0,
        "missingEmbedding": missing,
        "duplicatedDocIds": duplicated,
        "categories": categories,
        "indexes": indexes,
    }


# ---------------------------------------------------------------------------
# 実行計画で確かめる
# ---------------------------------------------------------------------------


def scan_of(plan: dict) -> dict:
    """実行計画の木から、走査ノードと並べ替えの有無を取り出す。"""
    node_types: list[str] = []
    scan: dict | None = None
    queue = [plan]
    while queue:
        node = queue.pop(0)
        node_types.append(node["Node Type"])
        if scan is None and node["Node Type"].endswith("Scan"):
            scan = node
        queue.extend(node.get("Plans", []))
    return {
        "nodeType": scan["Node Type"] if scan else "",
        "indexName": (scan or {}).get("Index Name"),
        "sorted": "Sort" in node_types,
        "nodeTypes": node_types,
    }


def explain(conn, vector: list[float], *, use_index: bool, top_k: int = TOP_K) -> dict:
    """索引を使う／使わないを**強制して**、計画と結果を取る。

    12行しかない表では、どちらの計画が選ばれるかは統計とコスト見積もりで決まります。
    比べたいのは「選ばれ方」ではなく「使ったときと使わないときの違い」なので、
    planner の設定で経路を固定します。

      索引あり: `enable_seqscan = off` ＋ `enable_sort = off`
                → 並べ替えの要らない HNSW の順序付き走査しか残らない
      索引なし: `enable_indexscan = off`（＋ index only scan も止める）
                → 素の走査＋並べ替えになる

    `SET LOCAL` はこのトランザクションの中だけに効きます。最後に `rollback` すれば
    設定は確実に元へ戻るので、後続の検証に影響しません。
    """
    with conn.cursor() as cur:
        if use_index:
            cur.execute("SET LOCAL enable_seqscan = off")
            cur.execute("SET LOCAL enable_sort = off")
        else:
            cur.execute("SET LOCAL enable_indexscan = off")
            cur.execute("SET LOCAL enable_indexonlyscan = off")
        cur.execute("EXPLAIN (FORMAT JSON) " + SEARCH_SQL, (vector, top_k))
        plan = cur.fetchone()[0][0]["Plan"]
        cur.execute(SEARCH_SQL, (vector, top_k))
        docs = [row[0] for row in cur.fetchall()]
    conn.rollback()
    return {**scan_of(plan), "docIds": docs}


def compare_plans(conn, runtime, query: str = GOLDEN_QUERY) -> dict:
    """同じクエリを、索引ありと索引なしの2通りで実行して比べる。"""
    vector = vector_store.embed_text(runtime, query)
    with_index = explain(conn, vector, use_index=True)
    without_index = explain(conn, vector, use_index=False)
    return {
        "query": query,
        "withIndex": with_index,
        "withoutIndex": without_index,
        "sameResult": with_index["docIds"] == without_index["docIds"],
    }


# ---------------------------------------------------------------------------
# 母集団を先に絞る
# ---------------------------------------------------------------------------


def prefilter_counts(conn, categories: tuple[str, ...] = CATEGORIES) -> dict:
    """カテゴリごとの候補件数。**絞ってから並べるほど速い。**"""
    return vector_store.category_counts(conn, list(categories))


# ---------------------------------------------------------------------------
# 索引の劣化を見張る
# ---------------------------------------------------------------------------


def golden_check(conn, runtime, *, query: str = GOLDEN_QUERY, expected: str = GOLDEN_TOP1):
    """定点クエリの1位が期待どおりかを確かめる。

    近似最近傍探索（HNSW）は**速いが正しさを保証しない**仕組みです。索引の再構築や
    データの入れ替えで1位が入れ替わることがあるため、運用では固定のクエリ集合を
    定期的に流し、順位の変化を検知します。評価指標そのものの設計は
    「セッション18：生成AIの評価システム」で扱います。
    """
    results = vector_store.search(conn, runtime, query, top_k=TOP_K)
    top1 = results[0]["doc_id"] if results else None
    return {"top1": top1, "expected": expected, "ok": top1 == expected,
            "returned": len(results)}


# ---------------------------------------------------------------------------
# 演習の本体
# ---------------------------------------------------------------------------


def main() -> None:
    runtime = clients.bedrock_runtime()
    conn = vector_store.connect()
    try:
        print("=== 1. 母集団を固定する（セッション4の状態：1文書=1チャンク） ===")
        state = baseline(conn, runtime)
        print(
            f"  行数 {state['rows']} / 次元 {state['dims']}"
            f" / 埋め込みが空の行 {state['missingEmbedding']}"
            f" / doc_id の重複 {state['duplicatedDocIds']}"
            f" / カテゴリ {state['categories']}種"
        )
        for name in (HNSW_INDEX, *META_INDEXES):
            print(f"  索引 {name}: {'あり' if name in state['indexes'] else 'なし'}")
        print(
            f"  {HNSW_INDEX} は vector_cosine_ops:"
            f" {'vector_cosine_ops' in state['indexes'][HNSW_INDEX]}"
        )

        print()
        print("=== 2. 索引を使う検索と使わない検索（EXPLAIN で確かめる） ===")
        compared = compare_plans(conn, runtime)
        print(f"  クエリ: {compared['query']}")
        with_index = compared["withIndex"]
        without_index = compared["withoutIndex"]
        print(
            f"  [索引あり] {with_index['nodeType']} using {with_index['indexName']}"
            f" / 並べ替えノード: {'あり' if with_index['sorted'] else 'なし'}"
        )
        print(
            f"  [索引なし] {without_index['nodeType']}"
            f" / 並べ替えノード: {'あり' if without_index['sorted'] else 'なし'}"
        )
        print(f"  上位{TOP_K}件の doc_id が一致: {compared['sameResult']}")
        print("  12行では素の走査でも十分に速いため、既定の計画は環境で変わります")
        print("  だから「速いはず」ではなく EXPLAIN で確かめます")

        print()
        print("=== 3. 母集団を先に絞る（メタデータフィルタ） ===")
        counts = prefilter_counts(conn)
        print(f"  絞らない: {state['rows']} 件")
        for category, count in counts.items():
            print(f"  category={category}: {count} 件")
        print("  絞るほど並べ替える件数が減ります（索引が効くのは絞った後の話）")

        print()
        print("=== 4. 索引の劣化を見張る（定点クエリ） ===")
        golden = golden_check(conn, runtime)
        print(
            f"  クエリ「{GOLDEN_QUERY}」の1位: {golden['top1']}"
            f"（期待どおり: {golden['ok']}）"
        )
        print(f"  返した件数: {golden['returned']} 件")
        print("  近似最近傍は速いが正しさを保証しません。1位が変わったら索引を疑います")
    finally:
        conn.close()


if __name__ == "__main__":
    main()

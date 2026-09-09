#!/usr/bin/env python3
"""セッション5: 検索機構ラボ（OpenSearch を使わない部分）。

分け方 → ベクトル化 → 検索方式 → 並べ替え → クエリの加工、という5段の意思決定を
順に観察します。既定の4サービスだけで動きます。

    docker compose exec app python src/session05/retrieval_lab.py
"""

from __future__ import annotations

import sys

sys.path.insert(0, "/workspace")
sys.path.insert(0, "/workspace/src/session04")
sys.path.insert(0, "/workspace/src/session05")

from awskit import clients  # noqa: E402

import chunking  # noqa: E402
import retriever  # noqa: E402
import vector_store  # noqa: E402

# キーワード側を効かせるため、語を半角スペースで区切ったクエリを使う
QUERY = "有給休暇 繰越 上限"
QUESTION = "有給休暇の繰越上限は何日ですか？"

# 「丸ごと1つのチャンクに入っていてほしい文」（hr-001 の2文目）
PROBE = "未消化分は翌年度に限り繰り越せますが、繰越上限は20日です。"

STRATEGIES = [
    ("1文書=1チャンク", lambda t: [t]),
    ("固定長50・重なりなし", lambda t: chunking.fixed_size(t, size=50)),
    ("固定長50・重なり15", lambda t: chunking.fixed_size(t, size=50, overlap=15)),
    ("文単位・上限50文字", lambda t: chunking.sentence_windows(t, max_chars=50)),
    ("文単位・上限140文字", lambda t: chunking.sentence_windows(t, max_chars=140)),
]


def reset_table(conn) -> None:
    """分け方を変えるときは全件作り直す。

    分け方を変えると `chunk_index` の対応が崩れるため、UPSERT では古いチャンクが
    残ります（セッション4の prune は `doc_id` 単位の削除なので拾えません）。
    """
    with conn.cursor() as cur:
        cur.execute("TRUNCATE doc_chunks")
    conn.commit()


def ids(hits: list[dict], doc_id_by_uri: dict[str, str]) -> list[str]:
    """`Retrieve` の結果を doc_id の並びにして、比べやすくする。"""
    return [doc_id_by_uri.get(hit["uri"], hit["uri"]) for hit in hits]


def main() -> int:
    runtime = clients.bedrock_runtime()
    agent = clients.agent_runtime()
    documents = chunking.load_documents()
    doc_id_by_uri = {doc["uri"]: doc["id"] for doc in documents}
    target = next(doc for doc in documents if doc["id"] == "hr-001")

    print("=== セッション5: 検索機構ラボ ===")
    print(f"埋め込みモデル: {vector_store.EMBED_MODEL_ID} / クエリ: {QUERY}")
    print()

    # ------------------------------------------------------------------
    sentences = chunking.split_sentences(target["text"])
    print(
        f"--- 1. 分け方の比較（hr-001「{target['title']}」"
        f"全{len(target['text'])}文字・{len(sentences)}文）---"
    )
    print("戦略 | チャンク数 | 最長 | 文の途中で切れた数 | 文2を丸ごと含む")
    for label, chunker in STRATEGIES:
        report = chunking.strategy_report(chunker(target["text"]), probe=PROBE)
        print(
            f"{label} | {report['count']} | {report['longest']} | {report['cut_mid']} | "
            f"{'あり' if report['has_probe'] else 'なし'}"
        )
    print()

    # ------------------------------------------------------------------
    with vector_store.connect() as conn:
        print("--- 2. コーパス全体を分け方別に投入して上位3件を見る（pgvector）---")
        print("戦略 | 索引の行数 | 上位3件の合計文字数 | 上位3件に出典が全件付く")
        for label, chunker in STRATEGIES[:3]:
            reset_table(conn)
            vector_store.sync(conn, runtime, chunking.chunk_corpus(documents, chunker))
            hits = vector_store.search(conn, runtime, QUERY, top_k=3)
            print(
                f"{label} | {vector_store.row_count(conn)} | "
                f"{sum(len(h['content']) for h in hits)} | "
                f"{'はい' if all(h['source_uri'] for h in hits) else 'いいえ'}"
            )
        print()

        # --------------------------------------------------------------
        print("--- 3. 子で当てて親を返す（small-to-big）---")
        reset_table(conn)
        vector_store.sync(
            conn, runtime, chunking.chunk_corpus(documents, lambda t: chunking.fixed_size(t, size=50))
        )
        children = chunking.fixed_size(target["text"], size=50)
        parent = chunking.fetch_parent(conn, "hr-001")
        print(f"hr-001 の子チャンク数: {len(children)} / 最長 {max(len(c) for c in children)}文字")
        print(f"連結して復元した親: {len(parent)}文字 / 元の本文と一致: {'はい' if parent == target['text'] else 'いいえ'}")
        print(f"子チャンク単独で文2を丸ごと含むもの: {sum(1 for c in children if PROBE in c)}件")
        print(f"親には文2が含まれる: {'はい' if PROBE in parent else 'いいえ'}")
        print()

    # ------------------------------------------------------------------
    print("--- 4. 検索方式（Knowledge Bases の overrideSearchType）---")
    semantic = retriever.retrieve(agent, QUERY, search_type="SEMANTIC", top_k=3)
    hybrid = retriever.retrieve(agent, QUERY, search_type="HYBRID", top_k=3)
    print(f"SEMANTIC の上位3件: {ids(semantic, doc_id_by_uri)}")
    print(f"HYBRID   の上位3件: {ids(hybrid, doc_id_by_uri)}")
    print(f"SEMANTIC の1位と2位のスコア差: {semantic[0]['score'] - semantic[1]['score']:.6f}")
    print(f"HYBRID   の1位と2位のスコア差: {hybrid[0]['score'] - hybrid[1]['score']:.6f}")
    print()

    # ------------------------------------------------------------------
    print("--- 5. クエリの書き換え（キーワード側を効かせる）---")
    def semantic_by_uri(query: str) -> dict[str, float]:
        return {
            hit["uri"]: hit["score"]
            for hit in retriever.retrieve(agent, query, search_type="SEMANTIC", top_k=12)
        }

    raw_hybrid = retriever.retrieve(agent, QUESTION, search_type="HYBRID", top_k=3)
    raw_scores = semantic_by_uri(QUESTION)
    scores = semantic_by_uri(QUERY)
    print(f"原文:      {QUESTION}")
    print(f"書き換え後: {retriever.to_keywords(QUESTION)}")
    base = raw_scores[raw_hybrid[0]["uri"]] or 1e-9
    print(
        "原文の HYBRID 1位: SEMANTIC スコアの何倍か = "
        f"{raw_hybrid[0]['score'] / base:.3f}（0.7 ならキーワード一致が0）"
    )
    print(
        "書き換え後の HYBRID 1位: SEMANTIC スコアの 0.7 倍との差 = "
        f"{hybrid[0]['score'] - 0.7 * scores[hybrid[0]['uri']]:.3f}（0.3 ならキーワード全一致）"
    )
    print(f"書き換え後の HYBRID の上位3件: {ids(hybrid, doc_id_by_uri)}")
    print()

    # ------------------------------------------------------------------
    print("--- 6. リランク（順序を壊した候補を渡す）---")
    shuffled = list(reversed(retriever.retrieve(agent, QUERY, search_type="SEMANTIC", top_k=5)))
    reranked = retriever.rerank(agent, QUERY, shuffled, top_n=3)
    print(f"渡した順番: {ids(shuffled, doc_id_by_uri)}")
    print(f"リランク後: {ids(reranked, doc_id_by_uri)}")
    print(f"リランク後の1位と2位のスコア差: {reranked[0]['rerank_score'] - reranked[1]['rerank_score']:.6f}")
    print()

    # ------------------------------------------------------------------
    print("--- 7. 検索の共通入口（Retriever）---")
    for mode in retriever.MODES:
        print(f"mode={mode}: {ids(retriever.search(agent, QUERY, mode=mode, top_k=3), doc_id_by_uri)}")
    spec = retriever.TOOL_SPEC["toolSpec"]
    print(f"ツール名: {spec['name']} / 必須引数: {spec['inputSchema']['json']['required']}")
    print()

    # ------------------------------------------------------------------
    print("--- 8. 元の状態（1文書=1チャンク）へ戻す ---")
    with vector_store.connect() as conn:
        reset_table(conn)
        stats = vector_store.sync(conn, runtime, vector_store.load_chunks())
        print(f"行数: {vector_store.row_count(conn)} / 新規: {stats['inserted']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

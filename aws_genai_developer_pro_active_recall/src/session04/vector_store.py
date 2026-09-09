#!/usr/bin/env python3
"""セッション4: 自前のベクトルストア（Amazon Aurora PostgreSQL + pgvector 相当）。

「検索の器」を自分で持つ側の責任を、1つのモジュールに閉じ込めます。

    - 埋め込みを作る（Titan Text Embeddings V2 を invoke_model で呼ぶ）
    - メタデータと一緒に投入する（増分更新・変更検知・削除の反映）
    - コサイン距離で最近傍を引く（メタデータフィルタ付き）

チャンク分割と埋め込みモデルの選定は本章の対象外です。ここでは「1文書=1チャンク」
（`chunk_index` は常に 0）で投入します。分け方の設計は
「セッション5：検索機構の設計 — チャンキング・埋め込み・ハイブリッド・リランク」で扱います。
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, "/workspace")

import psycopg  # noqa: E402
from pgvector.psycopg import register_vector  # noqa: E402

from awskit import clients  # noqa: E402

# 埋め込みは実 AWS と同じ経路で作る（モデルを invoke_model で呼ぶ）。
# モックの内部関数を直接呼ばないのは、このコードがそのまま実 Bedrock で動くようにするため
EMBED_MODEL_ID = "amazon.titan-embed-text-v2:0"
EMBED_DIMENSIONS = 1024

CORPUS_PATH = Path("/workspace/fixtures/kb_corpus.json")

# 冪等な取り込みの核。UNIQUE (doc_id, chunk_index) があるので、
# 同じチャンクを何度投入しても行は増えず、最後の内容で上書きされる
UPSERT_SQL = """
INSERT INTO doc_chunks
    (doc_id, chunk_index, source_uri, title, category, updated_at, content, embedding)
VALUES (%s, %s, %s, %s, %s, %s::date, %s, %s::vector)
ON CONFLICT (doc_id, chunk_index) DO UPDATE SET
    source_uri = EXCLUDED.source_uri,
    title      = EXCLUDED.title,
    category   = EXCLUDED.category,
    updated_at = EXCLUDED.updated_at,
    content    = EXCLUDED.content,
    embedding  = EXCLUDED.embedding
"""


def connect() -> psycopg.Connection:
    """pgvector を載せた PostgreSQL へ接続する。

    `register_vector` は psycopg に `vector` 型を教える手続きです。
    ベクトル列を Python 側で受け取るときに必要になります。
    """
    conn = psycopg.connect(clients.pg_dsn())
    register_vector(conn)
    return conn


def content_hash(text: str) -> str:
    """本文のハッシュ。変更検知（差分だけ再計算する）の判定に使う。"""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def embed_text(runtime, text: str, dimensions: int = EMBED_DIMENSIONS) -> list[float]:
    """Titan Text Embeddings V2 で埋め込みを1件作る。

    `dimensions` は 256 / 512 / 1024 から選べます（既定は 1024）。
    次元を落とすと索引が小さく検索が速くなりますが、`doc_chunks.embedding` の
    列定義と一致していなければ投入時にエラーになります。
    """
    response = runtime.invoke_model(
        modelId=EMBED_MODEL_ID,
        body=json.dumps({"inputText": text, "dimensions": dimensions}),
    )
    payload = json.loads(response["body"].read())
    vector = payload["embedding"]
    if len(vector) != dimensions:
        raise RuntimeError(f"次元数が一致しません: {len(vector)} != {dimensions}")
    return vector


def load_chunks(path: Path = CORPUS_PATH) -> list[dict]:
    """社内文書12件を「投入する行」の形に整える（1文書=1チャンク）。

    メタデータは検索精度と説明責任の両方に効くため、本文と同時に必ず持たせます。
    - `source_uri`：回答に添える出典（引用表示）
    - `category`：カテゴリで絞る（部門・文書種別）
    - `updated_at`：古い版を除外する（鮮度）
    """
    with open(path, encoding="utf-8") as f:
        documents = json.load(f)
    return [
        {
            "doc_id": doc["id"],
            "chunk_index": 0,
            "source_uri": doc["uri"],
            "title": doc["title"],
            "category": doc["category"],
            "updated_at": doc["updatedAt"],
            "content": doc["text"],
        }
        for doc in documents
    ]


def stored_hashes(conn) -> dict[tuple[str, int], str]:
    """いま索引に入っているチャンクの本文ハッシュを読む。"""
    with conn.cursor() as cur:
        cur.execute("SELECT doc_id, chunk_index, content FROM doc_chunks")
        return {(row[0], row[1]): content_hash(row[2]) for row in cur.fetchall()}


def sync(conn, runtime, chunks: list[dict], *, prune: bool = True) -> dict[str, int]:
    """取り込み元の状態に索引を合わせる（増分更新）。

    1. 本文のハッシュが変わっていないチャンクは埋め込みを作り直さない（`skipped`）
    2. 変わったチャンクだけ埋め込みを作って UPSERT する（`inserted` / `updated`）
    3. 取り込み元から消えた文書は索引からも削除する（`deleted`）

    全件再構築は「常に正しいが常に高い」方式です。増分更新は
    「埋め込みの呼び出し回数 ≒ 変更件数」に抑えられます。
    """
    stats = {"inserted": 0, "updated": 0, "skipped": 0, "deleted": 0}
    existing = stored_hashes(conn)

    with conn.cursor() as cur:
        for chunk in chunks:
            key = (chunk["doc_id"], chunk["chunk_index"])
            if existing.get(key) == content_hash(chunk["content"]):
                stats["skipped"] += 1
                continue
            vector = embed_text(runtime, chunk["content"])
            cur.execute(
                UPSERT_SQL,
                (
                    chunk["doc_id"],
                    chunk["chunk_index"],
                    chunk["source_uri"],
                    chunk["title"],
                    chunk["category"],
                    chunk["updated_at"],
                    chunk["content"],
                    vector,
                ),
            )
            stats["updated" if key in existing else "inserted"] += 1

        if prune:
            keep = [chunk["doc_id"] for chunk in chunks]
            cur.execute("DELETE FROM doc_chunks WHERE doc_id <> ALL(%s)", (keep,))
            stats["deleted"] = cur.rowcount

    conn.commit()
    return stats


def _filter_clause(category: str | None, updated_from: str | None):
    """メタデータフィルタを WHERE 句に組み立てる。

    ベクトル検索の前に母集団を絞るため、`category` と `updated_at` には
    B-tree 索引を張ってあります（`sql/001-init-pgvector.sql`）。
    """
    clauses: list[str] = []
    params: list[object] = []
    if category is not None:
        clauses.append("category = %s")
        params.append(category)
    if updated_from is not None:
        clauses.append("updated_at >= %s::date")
        params.append(updated_from)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    return where, params


def search(
    conn,
    runtime,
    query: str,
    *,
    top_k: int = 3,
    category: str | None = None,
    updated_from: str | None = None,
) -> list[dict]:
    """コサイン距離（`<=>`）で最近傍を引く。

    `<=>` はコサイン距離（1 - コサイン類似度）です。HNSW 索引を
    `vector_cosine_ops` で作っているため、この演算子で並べたときだけ索引が効きます。
    """
    vector = embed_text(runtime, query)
    where, filter_params = _filter_clause(category, updated_from)
    sql = f"""
        SELECT doc_id, title, category, updated_at, source_uri, content,
               1 - (embedding <=> %s::vector) AS similarity
        FROM doc_chunks
        {where}
        ORDER BY embedding <=> %s::vector
        LIMIT %s
    """
    params = [vector, *filter_params, vector, top_k]
    with conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()
    return [
        {
            "doc_id": row[0],
            "title": row[1],
            "category": row[2],
            "updated_at": row[3],
            "source_uri": row[4],
            "content": row[5],
            "similarity": float(row[6]),
        }
        for row in rows
    ]


def candidates(
    conn, *, category: str | None = None, updated_from: str | None = None
) -> list[str]:
    """フィルタが選ぶ母集団（doc_id の一覧）。フィルタの効き方を確認するために使う。"""
    where, params = _filter_clause(category, updated_from)
    with conn.cursor() as cur:
        cur.execute(f"SELECT doc_id FROM doc_chunks {where} ORDER BY doc_id", params)
        return [row[0] for row in cur.fetchall()]


def row_count(conn) -> int:
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM doc_chunks")
        return int(cur.fetchone()[0])


def category_counts(conn, categories: list[str]) -> dict[str, int]:
    """カテゴリ別の件数。出力順を固定するため、カテゴリ名を引数で受け取る。"""
    counts: dict[str, int] = {}
    with conn.cursor() as cur:
        for category in categories:
            cur.execute(
                "SELECT count(*) FROM doc_chunks WHERE category = %s", (category,)
            )
            counts[category] = int(cur.fetchone()[0])
    return counts

-- ベクトルストアの初期化。コンテナの初回起動時に自動実行される。
-- Amazon Aurora PostgreSQL で pgvector を使うときと同じ手順（拡張の有効化 → 列型 vector）。

CREATE EXTENSION IF NOT EXISTS vector;

-- 検索対象のチャンク。1行 = 1チャンク（文書そのものではない）
CREATE TABLE IF NOT EXISTS doc_chunks (
    id           BIGSERIAL PRIMARY KEY,
    doc_id       TEXT        NOT NULL,           -- 元文書の識別子
    chunk_index  INT         NOT NULL,           -- 文書内のチャンク番号（0 始まり）
    source_uri   TEXT        NOT NULL,           -- S3 の場所。引用表示に使う
    title        TEXT        NOT NULL,
    category     TEXT        NOT NULL,           -- メタデータフィルタの対象
    updated_at   DATE        NOT NULL,
    content      TEXT        NOT NULL,
    -- 次元数は Amazon Titan Text Embeddings V2 の既定に合わせる
    embedding    vector(1024),
    UNIQUE (doc_id, chunk_index)
);

-- 近似最近傍探索用のインデックス。
-- HNSW はビルドが重いが検索が速い。コサイン距離で検索するので vector_cosine_ops を使う
CREATE INDEX IF NOT EXISTS doc_chunks_embedding_hnsw
    ON doc_chunks USING hnsw (embedding vector_cosine_ops);

-- メタデータフィルタを併用する検索のため、絞り込み列にも索引を張る
CREATE INDEX IF NOT EXISTS doc_chunks_category_idx ON doc_chunks (category);
CREATE INDEX IF NOT EXISTS doc_chunks_updated_at_idx ON doc_chunks (updated_at);

-- 本書の共通スキーマ（PostgreSQL 側）。初回起動時に自動実行される。
-- データの投入は tools/seed_pg.sql が行う（verify-all.sh の冒頭で実行）。

-- 内部構造を覗くための拡張
CREATE EXTENSION IF NOT EXISTS pg_stat_statements;  -- クエリ別の統計
CREATE EXTENSION IF NOT EXISTS pageinspect;         -- ページ・B+木の中身を直接読む
CREATE EXTENSION IF NOT EXISTS pgstattuple;         -- 断片化・不要行の割合
CREATE EXTENSION IF NOT EXISTS btree_gin;           -- 複合インデックスの比較用

CREATE TABLE customers (
    id          integer      PRIMARY KEY,
    name        text         NOT NULL,
    email       text         NOT NULL,
    region      text         NOT NULL,
    created_at  timestamptz  NOT NULL
);

CREATE TABLE products (
    id          integer      PRIMARY KEY,
    name        text         NOT NULL,
    category    text         NOT NULL,
    price       integer      NOT NULL CHECK (price >= 0),
    stock       integer      NOT NULL CHECK (stock >= 0)
);

CREATE TABLE orders (
    id           bigint       PRIMARY KEY,
    customer_id  integer      NOT NULL REFERENCES customers(id),
    ordered_at   timestamptz  NOT NULL,
    status       text         NOT NULL CHECK (status IN ('completed', 'pending', 'cancelled'))
);

CREATE TABLE order_items (
    id          bigserial    PRIMARY KEY,
    order_id    bigint       NOT NULL REFERENCES orders(id),
    product_id  integer      NOT NULL REFERENCES products(id),
    quantity    integer      NOT NULL CHECK (quantity > 0),
    unit_price  integer      NOT NULL CHECK (unit_price >= 0)
);

-- 意図的にインデックスは主キーと外部キー制約が作るものだけにしておく。
-- 「インデックスがない状態の実行計画」を最初に観察させるため（S03 で読者が自分で追加する）。

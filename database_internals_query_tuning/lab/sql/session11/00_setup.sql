-- S11-00 作業用テーブルを作り直す（何度実行してもよい）
-- 4テーブルの行は変えないよう、在庫の実験は products をコピーした s11_products で行う。
-- s11_order_lines は外部キーのロック（03）、s11_jobs はジョブキュー（04）で使う。
-- 各実験ファイルの最初の手順で \i sql/session11/00_setup.sql として呼び出す（メッセージを出さずに作り直す）
\set QUIET on
SET client_min_messages = warning;
DROP TABLE IF EXISTS s11_order_lines, s11_products, s11_jobs;
CREATE TABLE s11_products AS SELECT * FROM products;
ALTER TABLE s11_products ADD PRIMARY KEY (id);
CREATE TABLE s11_order_lines (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  product_id integer NOT NULL REFERENCES s11_products (id),
  quantity integer NOT NULL
);
CREATE TABLE s11_jobs (id integer PRIMARY KEY, status text NOT NULL, worker text);
INSERT INTO s11_jobs SELECT g, 'queued', NULL FROM generate_series(1, 10) AS g;
VACUUM (ANALYZE) s11_products, s11_jobs;
RESET client_min_messages;
\set QUIET off

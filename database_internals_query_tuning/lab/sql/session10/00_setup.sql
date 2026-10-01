-- S10-00 作業用テーブルを作り直す（何度実行してもよい）
-- 4テーブルの行は変えないよう、在庫の実験は products の先頭5行をコピーした s10_products で行う。
-- 当直表 s10_oncall は書き込みスキューの実験（08）で使う。
-- 各実験ファイルの最初の手順で \i sql/session10/00_setup.sql として呼び出す（メッセージを出さずに作り直す）
\set QUIET on
SET client_min_messages = warning;
DROP TABLE IF EXISTS s10_products, s10_oncall;
CREATE TABLE s10_products AS
  SELECT id, name, category, stock FROM products WHERE id <= 5;
ALTER TABLE s10_products ADD PRIMARY KEY (id);
CREATE TABLE s10_oncall (doctor text PRIMARY KEY, on_call boolean NOT NULL);
INSERT INTO s10_oncall VALUES ('佐藤', true), ('鈴木', true);
RESET client_min_messages;
\set QUIET off

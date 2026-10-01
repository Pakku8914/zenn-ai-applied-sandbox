-- R03-04 ALTER TABLE がテーブルを書き換えるかどうか：relfilenode（ファイルの番号）が変われば書き換えた
-- \i sql/review03/04_add_column_rewrite.sql（01 の後。10 秒ほど）。どれも ACCESS EXCLUSIVE ロックを取る点は同じ（02 の (7)(8)）
CREATE OR REPLACE TEMP VIEW r03_files AS
SELECT (SELECT relfilenode FROM pg_class WHERE relname = 'r03_orders') AS table_file,
       (SELECT relfilenode FROM pg_class WHERE relname = 'r03_orders_pkey') AS pkey_file,
       pg_size_pretty(pg_relation_size('r03_orders')) AS table_size;
SELECT * FROM r03_files;
\timing on
-- (1) 列の追加（既定値なし）：書き換えない
ALTER TABLE r03_orders ADD COLUMN note text;
-- (2) 定数の既定値つき・NOT NULL の列の追加：PostgreSQL 11 以降は書き換えない（既定値をカタログに持つ）
ALTER TABLE r03_orders ADD COLUMN is_gift boolean NOT NULL DEFAULT false;
\timing off
SELECT * FROM r03_files;
-- 既存の行には is_gift の値が書かれておらず、カタログの「欠けている値」（attmissingval）で補っている
SELECT attname, atthasmissing, attmissingval FROM pg_attribute
WHERE attrelid = 'r03_orders'::regclass AND attname IN ('note', 'is_gift');
\timing on
-- (3) 行ごとに値が変わる既定値（clock_timestamp()）の列の追加：全行に値を書くため書き換える
ALTER TABLE r03_orders ADD COLUMN imported_at timestamptz DEFAULT clock_timestamp();
\timing off
SELECT * FROM r03_files;
\timing on
-- (4) 型の変更 integer → bigint：書き換える（インデックスも作り直される）
ALTER TABLE r03_orders ALTER COLUMN customer_id TYPE bigint;
\timing off
SELECT * FROM r03_files;
\timing on
-- (5) text → varchar(20)：長さの上限を付ける型変換なので書き換える（relfilenode が変わる）
ALTER TABLE r03_orders ALTER COLUMN status TYPE varchar(20);
\timing off
SELECT * FROM r03_files;
\timing on
-- (6) varchar(20) → varchar(30)（長さを広げるだけ）：書き換えない・全件も読まない
ALTER TABLE r03_orders ALTER COLUMN status TYPE varchar(30);
\timing off
SELECT * FROM r03_files;

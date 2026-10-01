-- Final-11 インデックス設計の書き込みコスト：同じ INSERT / UPDATE を、改善前と改善後のインデックス構成で比べる
-- 4 テーブルの行は変えられないので、orders・order_items と同じ大きさの作業用コピーに、それぞれの構成のインデックスを貼って測る
-- 10 秒ほどかかり、ディスクを一時的に 1GB ほど使う（最後に片付ける）。10 の後に実行する
-- 時間は EXPLAIN (ANALYZE, TIMING OFF, WAL) の Execution Time を交互に 5 回ずつ取った中央値。環境によって変わるので倍率で比べる。
-- 同時に WAL（変更の記録）の件数・量と、そのうちページ丸ごとの書き出し（FPI：チェックポイント後に初めて変更したページ）の数も取る
SET client_min_messages = warning;
DROP TABLE IF EXISTS final_w_orders_before, final_w_orders_after, final_w_orders_ref,
                     final_w_items_before, final_w_items_plain, final_w_items_after;
RESET client_min_messages;

-- (1) コピーを作る（orders 100 万行 × 3、order_items 200 万行 × 3）。id の順に入れて、元の表と同じ詰まり方にする
CREATE TABLE final_w_orders_before (LIKE orders) WITH (autovacuum_enabled = false);
CREATE TABLE final_w_orders_after  (LIKE orders) WITH (autovacuum_enabled = false);
CREATE TABLE final_w_orders_ref    (LIKE orders) WITH (autovacuum_enabled = false);
CREATE TABLE final_w_items_before  (LIKE order_items) WITH (autovacuum_enabled = false);
CREATE TABLE final_w_items_plain   (LIKE order_items) WITH (autovacuum_enabled = false);
CREATE TABLE final_w_items_after   (LIKE order_items) WITH (autovacuum_enabled = false);
INSERT INTO final_w_orders_before SELECT * FROM orders ORDER BY id;
INSERT INTO final_w_orders_after  SELECT * FROM orders ORDER BY id;
INSERT INTO final_w_orders_ref    SELECT * FROM orders ORDER BY id;
INSERT INTO final_w_items_before  SELECT * FROM order_items ORDER BY id;
INSERT INTO final_w_items_plain   SELECT * FROM order_items ORDER BY id;
INSERT INTO final_w_items_after   SELECT * FROM order_items ORDER BY id;

-- 改善前の構成：主キー ＋ orders (status)
ALTER TABLE final_w_orders_before ADD PRIMARY KEY (id);
CREATE INDEX ON final_w_orders_before (status);
ALTER TABLE final_w_items_before ADD PRIMARY KEY (id);
-- 改善後の構成（10 と同じ）：主キー ＋ orders (customer_id)・order_items (order_id) INCLUDE (...)
ALTER TABLE final_w_orders_after ADD PRIMARY KEY (id);
CREATE INDEX ON final_w_orders_after (customer_id);
ALTER TABLE final_w_items_after ADD PRIMARY KEY (id);
CREATE INDEX ON final_w_items_after (order_id) INCLUDE (product_id, quantity, unit_price);
-- 比較用 1：入れなかった orders (ordered_at) も足した場合
ALTER TABLE final_w_orders_ref ADD PRIMARY KEY (id);
CREATE INDEX ON final_w_orders_ref (customer_id);
CREATE INDEX ON final_w_orders_ref (ordered_at);
-- 比較用 2：明細のインデックスをカバリングにしない場合
ALTER TABLE final_w_items_plain ADD PRIMARY KEY (id);
CREATE INDEX ON final_w_items_plain (order_id);
VACUUM (ANALYZE) final_w_orders_before, final_w_orders_after, final_w_orders_ref,
                 final_w_items_before, final_w_items_plain, final_w_items_after;

-- (2) 1 回実行して、時間（ミリ秒）・WAL の件数・FPI の数・量（バイト）・共有バッファの外から読んだページ数を記録する道具。
--     pg_temp に作るので接続を切ると消える
DROP TABLE IF EXISTS pg_temp.final_write_timing;
CREATE TEMP TABLE final_write_timing (op text, variant text, round int, ms numeric,
                                      wal_records bigint, wal_fpi bigint, wal_bytes bigint, shared_read bigint);
CREATE OR REPLACE FUNCTION pg_temp.final_measure(op text, variant text, r int, q text) RETURNS void
LANGUAGE plpgsql AS $$
DECLARE j json;
BEGIN
  EXECUTE 'EXPLAIN (ANALYZE, TIMING OFF, WAL, BUFFERS, FORMAT JSON) ' || q INTO j;
  INSERT INTO final_write_timing VALUES (op, variant, r,
    round((j -> 0 ->> 'Execution Time')::numeric, 3),
    (j -> 0 -> 'Plan' ->> 'WAL Records')::bigint,
    (j -> 0 -> 'Plan' ->> 'WAL FPI')::bigint,
    (j -> 0 -> 'Plan' ->> 'WAL Bytes')::bigint,
    (j -> 0 -> 'Plan' ->> 'Shared Read Blocks')::bigint);
END $$;

-- (3) 交互に 5 回。毎回、新しい 1 万件の注文（と約 2 万行の明細）を足し、別の 1 万件の注文の status を「キャンセル」に書き換える。
--     本番と同じく 1 文ずつ別のトランザクションで実行する（\gexec は SELECT の結果の各行を 1 つの文として順に実行する。
--     \o /dev/null で、その 45 回ぶんの表示を捨てる）
--     新しい注文は、既存の注文 lo+1〜hi を 1 年後の日付・100 万番台の番号で複製したもの。更新するのは注文 500001 からの 1 万件ずつ
\o /dev/null
SELECT format('SELECT pg_temp.final_measure(%L, %L, %s, %L)', m.op, m.variant, r,
              format(m.sql, m.tbl, (r - 1) * 10000, r * 10000))
FROM generate_series(1, 5) AS r,
     (VALUES
       (1, 'INSERT orders 1万件', '改善前', 'final_w_orders_before',
        $q$INSERT INTO %I SELECT id + 1000000, customer_id, ordered_at + interval '1 year', status FROM orders WHERE id > %s AND id <= %s$q$),
       (2, 'INSERT orders 1万件', '改善後', 'final_w_orders_after',
        $q$INSERT INTO %I SELECT id + 1000000, customer_id, ordered_at + interval '1 year', status FROM orders WHERE id > %s AND id <= %s$q$),
       (3, 'INSERT orders 1万件', '参考:ordered_atあり', 'final_w_orders_ref',
        $q$INSERT INTO %I SELECT id + 1000000, customer_id, ordered_at + interval '1 year', status FROM orders WHERE id > %s AND id <= %s$q$),
       (4, 'INSERT order_items 約2万行', '改善前', 'final_w_items_before',
        $q$INSERT INTO %I SELECT id + 2000000, order_id + 1000000, product_id, quantity, unit_price FROM order_items WHERE order_id > %s AND order_id <= %s$q$),
       (5, 'INSERT order_items 約2万行', '改善後', 'final_w_items_after',
        $q$INSERT INTO %I SELECT id + 2000000, order_id + 1000000, product_id, quantity, unit_price FROM order_items WHERE order_id > %s AND order_id <= %s$q$),
       (6, 'INSERT order_items 約2万行', '参考:INCLUDEなし', 'final_w_items_plain',
        $q$INSERT INTO %I SELECT id + 2000000, order_id + 1000000, product_id, quantity, unit_price FROM order_items WHERE order_id > %s AND order_id <= %s$q$),
       (7, 'UPDATE orders 1万件', '改善前', 'final_w_orders_before',
        $q$UPDATE %I SET status = 'cancelled' WHERE id > 500000 + %s AND id <= 500000 + %s$q$),
       (8, 'UPDATE orders 1万件', '改善後', 'final_w_orders_after',
        $q$UPDATE %I SET status = 'cancelled' WHERE id > 500000 + %s AND id <= 500000 + %s$q$),
       (9, 'UPDATE orders 1万件', '参考:ordered_atあり', 'final_w_orders_ref',
        $q$UPDATE %I SET status = 'cancelled' WHERE id > 500000 + %s AND id <= 500000 + %s$q$)
     ) AS m(ord, op, variant, tbl, sql)
ORDER BY r, m.ord
\gexec
\o

-- (4) 中央値。時間は揺れる（チェックポイントの時期で FPI の数が、キャッシュの状態で読むページ数が変わる）ので、
--     WAL の件数と量、共有バッファの外から読んだページ数（最小〜最大）も並べる
SELECT op, variant,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY ms) AS median_ms,
       min(ms) AS min_ms, max(ms) AS max_ms,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY wal_records) AS wal_records,
       min(wal_fpi) AS min_fpi, max(wal_fpi) AS max_fpi,
       pg_size_pretty(percentile_cont(0.5) WITHIN GROUP (ORDER BY wal_bytes)::bigint) AS wal_bytes,
       min(shared_read) AS min_read, max(shared_read) AS max_read
FROM final_write_timing
GROUP BY op, variant
ORDER BY op, variant;

-- (5) 回ごとの UPDATE の時間と読んだページ数（揺れの正体を見る）
SELECT variant, string_agg(ms || ' ms / ' || shared_read || ' 頁', ',  ' ORDER BY round) AS rounds_1_to_5
FROM final_write_timing WHERE op LIKE 'UPDATE%' GROUP BY variant ORDER BY variant;

-- (6) HOT 更新（インデックスを書き換えずに済む更新）の件数と、コピーのインデックスの合計サイズ
SELECT pg_stat_force_next_flush();
SELECT relname, n_tup_upd, n_tup_hot_upd,
       (SELECT count(*) FROM pg_index WHERE indrelid = relid) AS indexes,
       pg_size_pretty(pg_indexes_size(relid)) AS index_total
FROM pg_stat_user_tables
WHERE relname ~ '^final_w_(orders|items)_'
ORDER BY relname;

-- (7) 片付け
DROP TABLE final_w_orders_before, final_w_orders_after, final_w_orders_ref,
           final_w_items_before, final_w_items_plain, final_w_items_after;

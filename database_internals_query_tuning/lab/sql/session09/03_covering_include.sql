-- S09-03 カバリング：INCLUDE で Index Only Scan を狙う
-- 題材は Mid01 の遅いクエリ A の後半（1 顧客の注文を新しい順に）。出発点から実行する

-- (1) customer_id の単一列インデックス：ヒープを 20 ページ読み、ソートする
CREATE INDEX orders_customer_id_idx ON orders (customer_id);
EXPLAIN (ANALYZE, BUFFERS)
SELECT id, ordered_at, status
FROM orders
WHERE customer_id = 12345
ORDER BY ordered_at DESC;

-- (2) 検索と並びに使う列をキーに、残りの列を INCLUDE に入れる：ヒープを読まず、ソートも無い
CREATE INDEX orders_customer_id_ordered_at_incl_idx ON orders (customer_id, ordered_at) INCLUDE (id, status);
EXPLAIN (ANALYZE, BUFFERS)
SELECT id, ordered_at, status
FROM orders
WHERE customer_id = 12345
ORDER BY ordered_at DESC;

-- (3) 大きさの比較：INCLUDE を付けないキーだけの版、全部をキーにした版も作って並べる
CREATE INDEX orders_customer_id_ordered_at_idx ON orders (customer_id, ordered_at);
CREATE INDEX orders_customer_id_ordered_at_id_status_idx ON orders (customer_id, ordered_at, id, status);
SELECT indexrelid::regclass AS index_name,
       pg_size_pretty(pg_relation_size(indexrelid)) AS size,
       pg_relation_size(indexrelid) / 8192 AS pages
FROM pg_index
WHERE indrelid = 'orders'::regclass
ORDER BY pg_relation_size(indexrelid), index_name;
SELECT pg_size_pretty(pg_relation_size('orders')) AS orders_table;

-- (4) Heap Fetches：Index Only Scan は Visibility Map（全行が見えるページの印）を頼りにヒープを読まずに済ませる
--     作業用コピー s09_orders は作った直後で、まだ VACUUM されていない（autovacuum も止める）
CREATE TABLE s09_orders WITH (autovacuum_enabled = false) AS SELECT * FROM orders;
CREATE INDEX s09_orders_customer_id_ordered_at_incl_idx ON s09_orders (customer_id, ordered_at) INCLUDE (id, status);
ANALYZE s09_orders;

-- (4a) Visibility Map が立っていないので、プランナは Index Only Scan を選ばない
EXPLAIN (ANALYZE, BUFFERS)
SELECT id, ordered_at, status
FROM s09_orders
WHERE customer_id = 12345
ORDER BY ordered_at DESC;

-- (4b) VACUUM で Visibility Map を立てると Index Only Scan になり、Heap Fetches は 0
VACUUM s09_orders;
EXPLAIN (ANALYZE, BUFFERS)
SELECT id, ordered_at, status
FROM s09_orders
WHERE customer_id = 12345
ORDER BY ordered_at DESC;

-- (4c) この顧客の 20 行を更新すると、その 20 ページの印が消え、Index Only Scan でもヒープを見に行く
UPDATE s09_orders SET status = status WHERE customer_id = 12345;
EXPLAIN (ANALYZE, BUFFERS)
SELECT id, ordered_at, status
FROM s09_orders
WHERE customer_id = 12345
ORDER BY ordered_at DESC;

-- (4d) もう一度 VACUUM すれば 0 に戻る。不要行が少ないと VACUUM はインデックスの掃除を省くことがあり、
--      そのページには印が立たないので、ここでは INDEX_CLEANUP ON で掃除を必ず行わせる（S12 で詳しく扱う）
VACUUM (INDEX_CLEANUP ON) s09_orders;
EXPLAIN (ANALYZE, BUFFERS)
SELECT id, ordered_at, status
FROM s09_orders
WHERE customer_id = 12345
ORDER BY ordered_at DESC;

-- 後片付け
DROP TABLE s09_orders;
DROP INDEX orders_customer_id_idx, orders_customer_id_ordered_at_incl_idx,
           orders_customer_id_ordered_at_idx, orders_customer_id_ordered_at_id_status_idx;

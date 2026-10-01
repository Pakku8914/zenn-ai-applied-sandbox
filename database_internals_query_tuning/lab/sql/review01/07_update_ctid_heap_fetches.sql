-- 横断復習①: 1 行の UPDATE が ctid と Index Only Scan の Heap Fetches に何を起こすか（S02・S05）。
-- 作業用コピー r01_customers で行う（自動 VACUUM が割り込まないよう止めておく）
CREATE TABLE r01_customers WITH (autovacuum_enabled = false) AS SELECT * FROM customers;
CREATE INDEX r01_customers_id_idx ON r01_customers (id);
VACUUM (ANALYZE) r01_customers;

SELECT ctid, id, name FROM r01_customers WHERE id = 500;
EXPLAIN (ANALYZE, BUFFERS) SELECT count(*) FROM r01_customers WHERE id <= 1000;

UPDATE r01_customers SET name = name WHERE id = 500;

SELECT ctid, id, name FROM r01_customers WHERE id = 500;
SELECT relpages FROM pg_class WHERE relname = 'r01_customers';
EXPLAIN (ANALYZE, BUFFERS) SELECT count(*) FROM r01_customers WHERE id <= 1000;

VACUUM r01_customers;
EXPLAIN (ANALYZE, BUFFERS) SELECT count(*) FROM r01_customers WHERE id <= 1000;

-- VACUUM の後も Heap Fetches が 0 に戻らない理由を VERBOSE で確かめ、インデックスの掃除を強制する
VACUUM (VERBOSE) r01_customers;
VACUUM (INDEX_CLEANUP ON) r01_customers;
EXPLAIN (ANALYZE, BUFFERS) SELECT count(*) FROM r01_customers WHERE id <= 1000;
SELECT count(*) AS ページ5の行数 FROM r01_customers WHERE (ctid::text::point)[0] = 5;

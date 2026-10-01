-- S14-03 pg_prewarm で事前に共有バッファへ読み込む。1 回目から shared hit になる
-- \i sql/session14/03_prewarm.sql
CREATE EXTENSION IF NOT EXISTS pg_buffercache;
CREATE EXTENSION IF NOT EXISTS pg_prewarm;
SET max_parallel_workers_per_gather = 0;
-- いったん追い出してから、テーブル全体を共有バッファに読み込む（戻り値は読み込んだページ数）
SELECT buffers_evicted FROM pg_buffercache_evict_relation('orders');
SELECT pg_prewarm('orders');
SELECT count(*) AS orders_buffers
FROM pg_buffercache WHERE relfilenode = pg_relation_filenode('orders')
  AND reldatabase = (SELECT oid FROM pg_database WHERE datname = current_database());
-- 02 と同じ Seq Scan。今度は 1 回目からすべて hit（すでに載っているページはリングバッファでも hit になる）
EXPLAIN (ANALYZE, BUFFERS) SELECT count(*) FROM orders;
RESET max_parallel_workers_per_gather;

-- S14 演習2 「1 回目が遅い」を pg_prewarm で消す：1 日分の注文（Bitmap Heap Scan）を、追い出した直後と読み込んだ直後で比べる
-- \i sql/session14/ex02_prewarm_first_run.sql
CREATE EXTENSION IF NOT EXISTS pg_buffercache;
CREATE EXTENSION IF NOT EXISTS pg_prewarm;
CREATE INDEX IF NOT EXISTS orders_ordered_at_idx ON orders (ordered_at);
SET max_parallel_workers_per_gather = 0;
-- (1) テーブルとインデックスを共有バッファから追い出した直後の 1 回目
SELECT buffers_evicted FROM pg_buffercache_evict_relation('orders');
SELECT buffers_evicted FROM pg_buffercache_evict_relation('orders_ordered_at_idx');
EXPLAIN (ANALYZE, BUFFERS)
SELECT * FROM orders WHERE ordered_at >= '2025-06-01' AND ordered_at < '2025-06-02';
-- (2) 追い出してから pg_prewarm で読み込んだ直後の 1 回目
SELECT buffers_evicted FROM pg_buffercache_evict_relation('orders');
SELECT buffers_evicted FROM pg_buffercache_evict_relation('orders_ordered_at_idx');
SELECT pg_prewarm('orders') AS heap_pages, pg_prewarm('orders_ordered_at_idx') AS index_pages;
EXPLAIN (ANALYZE, BUFFERS)
SELECT * FROM orders WHERE ordered_at >= '2025-06-01' AND ordered_at < '2025-06-02';
RESET max_parallel_workers_per_gather;

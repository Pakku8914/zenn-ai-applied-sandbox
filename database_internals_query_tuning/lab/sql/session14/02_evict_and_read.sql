-- S14-02 共有バッファから追い出した直後の読み取り：Buffers は read になるが、I/O の時間は小さい（OS のキャッシュから来る）
-- \i sql/session14/02_evict_and_read.sql
CREATE EXTENSION IF NOT EXISTS pg_buffercache;
SET max_parallel_workers_per_gather = 0;

-- (1) customers（516 ページ）を共有バッファから追い出す。buffers_evicted が追い出した枠の数
SELECT * FROM pg_buffercache_evict_relation('customers');
-- 追い出した直後の 1 回目：shared read（共有バッファに無く、OS に読みに行った）
EXPLAIN (ANALYZE, BUFFERS) SELECT count(*) FROM customers;
-- 2 回目：shared hit（1 回目に読んだページが共有バッファに残っている）
EXPLAIN (ANALYZE, BUFFERS) SELECT count(*) FROM customers;

-- (2) orders（8197 ページ = 64MB）で同じことをする
SELECT * FROM pg_buffercache_evict_relation('orders');
EXPLAIN (ANALYZE, BUFFERS) SELECT count(*) FROM orders;
EXPLAIN (ANALYZE, BUFFERS) SELECT count(*) FROM orders;
-- 2 回とも read になる理由：共有バッファの 1/4 より大きいテーブルの Seq Scan は、小さな「リングバッファ」だけを使い回す
-- （大きな表を 1 回なめただけで、ほかのよく使うページが追い出されないようにするため）。載っているページ数を見る
SELECT count(*) AS orders_buffers
FROM pg_buffercache WHERE relfilenode = pg_relation_filenode('orders')
  AND reldatabase = (SELECT oid FROM pg_database WHERE datname = current_database());
RESET max_parallel_workers_per_gather;

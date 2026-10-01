-- 練習（模範解答・発展）: 1 週間の Bitmap Heap Scan から lossy が消える work_mem の境界を二分探索する。
-- 前提: 01_create_indexes.sql 実行済み
SET max_parallel_workers_per_gather = 0;
SET work_mem = '128kB';
EXPLAIN (ANALYZE, COSTS OFF, TIMING OFF)
SELECT * FROM orders WHERE ordered_at >= '2025-06-01' AND ordered_at < '2025-06-08';
SET work_mem = '256kB';
EXPLAIN (ANALYZE, COSTS OFF, TIMING OFF)
SELECT * FROM orders WHERE ordered_at >= '2025-06-01' AND ordered_at < '2025-06-08';
SET work_mem = '176kB';
EXPLAIN (ANALYZE, COSTS OFF, TIMING OFF)
SELECT * FROM orders WHERE ordered_at >= '2025-06-01' AND ordered_at < '2025-06-08';
SET work_mem = '180kB';
EXPLAIN (ANALYZE, COSTS OFF, TIMING OFF)
SELECT * FROM orders WHERE ordered_at >= '2025-06-01' AND ordered_at < '2025-06-08';
RESET work_mem;
RESET max_parallel_workers_per_gather;

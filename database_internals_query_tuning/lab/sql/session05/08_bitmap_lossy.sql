-- Bitmap Heap Scan の Recheck Cond と、work_mem が足りないときの lossy（ページ単位）ビットマップ。
-- 並列実行が混ざると出力が読みにくいので、この節だけ並列を切る。
-- 前提: 01_create_indexes.sql 実行済み
SET max_parallel_workers_per_gather = 0;

-- (1) work_mem = 8MB（サンドボックスの既定）: 行単位（exact）のビットマップ
EXPLAIN (ANALYZE, BUFFERS)
SELECT * FROM orders WHERE ordered_at >= '2025-06-01' AND ordered_at < '2025-06-08';

-- (2) work_mem = 64kB: ビットマップが収まらず、一部のページが lossy（ページ単位）に落ちる
SET work_mem = '64kB';
EXPLAIN (ANALYZE, BUFFERS)
SELECT * FROM orders WHERE ordered_at >= '2025-06-01' AND ordered_at < '2025-06-08';

RESET work_mem;
RESET max_parallel_workers_per_gather;

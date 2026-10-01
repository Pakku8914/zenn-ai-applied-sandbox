-- S14-06 PostgreSQL の再起動直後（共有バッファが空）の 1 回目と 2 回目を比べる
-- 手順：(1) この章の 06 の前準備を psql で実行 → (2) ターミナルで docker compose restart pg → docker compose up -d --wait
--       → (3) docker compose exec lab psql -f sql/session14/06_after_restart.sql
-- 再起動で消えるのは PostgreSQL の共有バッファだけ。OS のページキャッシュ（Docker の VM のメモリ）は残る
-- 前準備（再起動の前に 1 回だけ）: CREATE INDEX IF NOT EXISTS orders_ordered_at_idx ON orders (ordered_at);
CREATE EXTENSION IF NOT EXISTS pg_buffercache;
SET max_parallel_workers_per_gather = 0;
-- 再起動直後の共有バッファ：ほとんど空
SELECT buffers_used, buffers_unused FROM pg_buffercache_summary();
-- 1 日分の注文（S03 の Bitmap Heap Scan）：1 回目は read、2 回目は hit
EXPLAIN (ANALYZE, BUFFERS)
SELECT * FROM orders WHERE ordered_at >= '2025-06-01' AND ordered_at < '2025-06-02';
EXPLAIN (ANALYZE, BUFFERS)
SELECT * FROM orders WHERE ordered_at >= '2025-06-01' AND ordered_at < '2025-06-02';
-- 全件の集計（Seq Scan）：1 回目も 2 回目も read（リングバッファ）。時間はほとんど変わらない
EXPLAIN (ANALYZE, BUFFERS) SELECT count(*) FROM orders;
EXPLAIN (ANALYZE, BUFFERS) SELECT count(*) FROM orders;
RESET max_parallel_workers_per_gather;

-- S09-ex01 列順の設計：2025 年 4〜6 月の cancelled（約 4.3%）の件数
-- 出発点から実行する。2 つの列順で、読んだインデックスのページ数（Buffers）と時間を比べる

CREATE INDEX orders_status_ordered_at_idx ON orders (status, ordered_at);
EXPLAIN (ANALYZE, BUFFERS)
SELECT count(*) FROM orders
WHERE status = 'cancelled'
  AND ordered_at >= '2025-04-01' AND ordered_at < '2025-07-01';
DROP INDEX orders_status_ordered_at_idx;

CREATE INDEX orders_ordered_at_status_idx ON orders (ordered_at, status);
EXPLAIN (ANALYZE, BUFFERS)
SELECT count(*) FROM orders
WHERE status = 'cancelled'
  AND ordered_at >= '2025-04-01' AND ordered_at < '2025-07-01';
DROP INDEX orders_ordered_at_status_idx;

-- 件数
SELECT count(*) FROM orders
WHERE status = 'cancelled'
  AND ordered_at >= '2025-04-01' AND ordered_at < '2025-07-01';

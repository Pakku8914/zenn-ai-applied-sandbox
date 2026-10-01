-- 横断復習①: 見積もり rows と actual rows のズレから問題を 2 つ見つける（S04・S05）。
CREATE INDEX orders_ordered_at_idx ON orders (ordered_at);
EXPLAIN (ANALYZE, BUFFERS) SELECT * FROM orders WHERE ordered_at::date = '2025-06-01';
EXPLAIN (ANALYZE, BUFFERS) SELECT * FROM orders WHERE ordered_at >= '2025-06-01' AND ordered_at < '2025-06-02';

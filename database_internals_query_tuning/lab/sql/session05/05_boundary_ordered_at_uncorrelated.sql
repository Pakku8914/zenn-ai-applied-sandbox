-- 物理的な並び順と相関しない orders.ordered_at の範囲で、同じように境界を探す。
-- 境界の「範囲の幅」は ANALYZE の標本抽出で前後するが、「見積もり rows」で見るとほぼ同じ所で切り替わる。
-- 前提: 01_create_indexes.sql 実行済み

-- (a) 範囲が狭いとき: Index Scan → Bitmap Heap Scan（見積もり 3 行と 4 行の間で切り替わる）
EXPLAIN SELECT * FROM orders
WHERE ordered_at >= '2025-06-01 00:00:00' AND ordered_at < '2025-06-01 00:01:00';   -- 60 秒

EXPLAIN SELECT * FROM orders
WHERE ordered_at >= '2025-06-01 00:00:00' AND ordered_at < '2025-06-01 00:05:00';   -- 300 秒

-- (b) 範囲が広いとき: Bitmap Heap Scan → Seq Scan（見積もり約 40.5 万行と 40.8 万行の間で切り替わる）
EXPLAIN SELECT * FROM orders
WHERE ordered_at >= '2025-01-01' AND ordered_at < '2025-01-31';   -- 30 日

EXPLAIN SELECT * FROM orders
WHERE ordered_at >= '2025-01-01' AND ordered_at < '2025-06-30';   -- 180 日

EXPLAIN SELECT * FROM orders
WHERE ordered_at >= '2025-01-01' AND ordered_at < '2025-05-21';   -- 140 日

EXPLAIN SELECT * FROM orders
WHERE ordered_at >= '2025-01-01' AND ordered_at < '2025-06-10';   -- 160 日

-- (c) Bitmap Scan を禁止すると、Index Scan はどこまで粘れるか（学習用。本番で enable_* を切り替えない）
SET enable_bitmapscan = off;
EXPLAIN SELECT * FROM orders
WHERE ordered_at >= '2025-06-01' AND ordered_at < '2025-06-02';   -- 1 日

EXPLAIN SELECT * FROM orders
WHERE ordered_at >= '2025-06-01' AND ordered_at < '2025-06-04';   -- 3 日
RESET enable_bitmapscan;

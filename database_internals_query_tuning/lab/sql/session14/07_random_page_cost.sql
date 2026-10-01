-- S14-07 random_page_cost を下げると、これまでの章で「プランナが最速でない計画を選んだ」例はどうなるか
-- \i sql/session14/07_random_page_cost.sql
-- ・random_page_cost はランダム読み 1 ページのコスト（既定 4。順次読み seq_page_cost = 1 の 4 倍＝回転するディスクを想定）
-- ・ここでの SET はこのセッションだけ。全データがメモリ（共有バッファか OS のキャッシュ）に載っているこの環境での実験で、推奨値ではない
-- ・計画を比べやすくするため、並列実行は止めておく
SET max_parallel_workers_per_gather = 0;
SHOW seq_page_cost;
SHOW random_page_cost;

-- (B) S07・Review02 の「1 週間分の文具の売上」。order_items(order_id) のインデックスだけがある状態
CREATE INDEX IF NOT EXISTS order_items_order_id_idx ON order_items (order_id);
DROP INDEX IF EXISTS orders_ordered_at_idx;
EXPLAIN (ANALYZE, BUFFERS)
SELECT sum(oi.quantity * oi.unit_price) AS sales, count(*) AS lines
FROM orders o
JOIN order_items oi ON oi.order_id = o.id
JOIN products p ON p.id = oi.product_id
WHERE o.ordered_at >= '2025-03-01' AND o.ordered_at < '2025-03-08'
  AND o.status <> 'cancelled'
  AND p.category = '文具';
SET random_page_cost = 1.1;
EXPLAIN (ANALYZE, BUFFERS)
SELECT sum(oi.quantity * oi.unit_price) AS sales, count(*) AS lines
FROM orders o
JOIN order_items oi ON oi.order_id = o.id
JOIN products p ON p.id = oi.product_id
WHERE o.ordered_at >= '2025-03-01' AND o.ordered_at < '2025-03-08'
  AND o.status <> 'cancelled'
  AND p.category = '文具';
RESET random_page_cost;

-- (A) S03・S05 の「1 日分の注文」。orders(ordered_at) のインデックスを作る
CREATE INDEX orders_ordered_at_idx ON orders (ordered_at);
EXPLAIN (ANALYZE, BUFFERS)
SELECT * FROM orders WHERE ordered_at >= '2025-06-01' AND ordered_at < '2025-06-02';
-- 1.1 では Bitmap Heap Scan のまま（Index Scan との差が縮むだけ）。比べるため Index Scan のコストも見る
SET random_page_cost = 1.1;
EXPLAIN SELECT * FROM orders WHERE ordered_at >= '2025-06-01' AND ordered_at < '2025-06-02';
SET enable_bitmapscan = off;
EXPLAIN SELECT * FROM orders WHERE ordered_at >= '2025-06-01' AND ordered_at < '2025-06-02';
RESET enable_bitmapscan;
-- 1.0（順次読みと同じ）まで下げると、プランナ自身が Index Scan を選ぶ
SET random_page_cost = 1.0;
EXPLAIN (ANALYZE, BUFFERS)
SELECT * FROM orders WHERE ordered_at >= '2025-06-01' AND ordered_at < '2025-06-02';
RESET random_page_cost;

-- (C) S08 の「全件を ordered_at 順に」。既定でも Index Scan（実測では Seq Scan ＋ Sort の方が速かった）。
--     random_page_cost を下げると Index Scan のコストがさらに下がるだけで、選択は変わらない
EXPLAIN SELECT * FROM orders ORDER BY ordered_at;
SET random_page_cost = 1.1;
EXPLAIN SELECT * FROM orders ORDER BY ordered_at;
RESET random_page_cost;

-- (D) S09 の「先頭列の種類が多い複合インデックスと、2 番目の列だけの条件」。既定は Seq Scan
DROP INDEX orders_ordered_at_idx;
CREATE INDEX orders_customer_id_ordered_at_idx ON orders (customer_id, ordered_at);
EXPLAIN (ANALYZE, BUFFERS)
SELECT count(*) FROM orders WHERE ordered_at >= '2025-06-01' AND ordered_at < '2025-06-02';
SET random_page_cost = 1.1;
EXPLAIN (ANALYZE, BUFFERS)
SELECT count(*) FROM orders WHERE ordered_at >= '2025-06-01' AND ordered_at < '2025-06-02';
RESET random_page_cost;
DROP INDEX orders_customer_id_ordered_at_idx;
RESET max_parallel_workers_per_gather;

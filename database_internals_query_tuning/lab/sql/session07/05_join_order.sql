-- S07-05 結合順序：プランナが並べ替えた場合と、書いた順に結合させた場合（join_collapse_limit = 1）
-- 1 日分の注文を orders(ordered_at) のインデックスで絞れるようにしておく（S05 で作ったものと同じ）
CREATE INDEX orders_ordered_at_idx ON orders (ordered_at);

SET max_parallel_workers_per_gather = 0;

-- (1) FROM に order_items → products → orders の順で書く。既定ではプランナが順序を並べ替える
EXPLAIN (ANALYZE, BUFFERS)
SELECT sum(oi.quantity * oi.unit_price) AS sales, count(*) AS lines
FROM order_items oi
JOIN products p ON p.id = oi.product_id
JOIN orders o ON o.id = oi.order_id
WHERE o.ordered_at >= '2025-03-01' AND o.ordered_at < '2025-03-02'
  AND o.status <> 'cancelled'
  AND p.category = '文具';

-- (2) join_collapse_limit = 1：明示的な JOIN を書いた順のまま結合させる
SET join_collapse_limit = 1;
EXPLAIN (ANALYZE, BUFFERS)
SELECT sum(oi.quantity * oi.unit_price) AS sales, count(*) AS lines
FROM order_items oi
JOIN products p ON p.id = oi.product_id
JOIN orders o ON o.id = oi.order_id
WHERE o.ordered_at >= '2025-03-01' AND o.ordered_at < '2025-03-02'
  AND o.status <> 'cancelled'
  AND p.category = '文具';

-- (3) join_collapse_limit = 1 のまま、絞り込める orders から書く
EXPLAIN (ANALYZE, BUFFERS)
SELECT sum(oi.quantity * oi.unit_price) AS sales, count(*) AS lines
FROM orders o
JOIN order_items oi ON oi.order_id = o.id
JOIN products p ON p.id = oi.product_id
WHERE o.ordered_at >= '2025-03-01' AND o.ordered_at < '2025-03-02'
  AND o.status <> 'cancelled'
  AND p.category = '文具';

RESET join_collapse_limit;
RESET max_parallel_workers_per_gather;

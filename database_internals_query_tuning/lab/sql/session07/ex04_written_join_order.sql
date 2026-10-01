-- S07 練習問題の模範解答：join_collapse_limit = 1（書いた順に結合）で、FROM の順序 3 通りを比べる
-- 前提：order_items(order_id) と orders(ordered_at) のインデックス（03・05 で作成）
CREATE INDEX IF NOT EXISTS order_items_order_id_idx ON order_items (order_id);
CREATE INDEX IF NOT EXISTS orders_ordered_at_idx ON orders (ordered_at);
SET max_parallel_workers_per_gather = 0;
SET join_collapse_limit = 1;

-- (a) orders → order_items → products
EXPLAIN (ANALYZE, TIMING OFF)
SELECT sum(oi.quantity * oi.unit_price) AS sales, count(*) AS lines
FROM orders o
JOIN order_items oi ON oi.order_id = o.id
JOIN products p ON p.id = oi.product_id
WHERE o.ordered_at >= '2025-03-01' AND o.ordered_at < '2025-03-02'
  AND o.status <> 'cancelled' AND p.category = '文具';

-- (b) order_items → products → orders
EXPLAIN (ANALYZE, TIMING OFF)
SELECT sum(oi.quantity * oi.unit_price) AS sales, count(*) AS lines
FROM order_items oi
JOIN products p ON p.id = oi.product_id
JOIN orders o ON o.id = oi.order_id
WHERE o.ordered_at >= '2025-03-01' AND o.ordered_at < '2025-03-02'
  AND o.status <> 'cancelled' AND p.category = '文具';

-- (c) products → order_items → orders
EXPLAIN (ANALYZE, TIMING OFF)
SELECT sum(oi.quantity * oi.unit_price) AS sales, count(*) AS lines
FROM products p
JOIN order_items oi ON oi.product_id = p.id
JOIN orders o ON o.id = oi.order_id
WHERE o.ordered_at >= '2025-03-01' AND o.ordered_at < '2025-03-02'
  AND o.status <> 'cancelled' AND p.category = '文具';

RESET join_collapse_limit;
RESET max_parallel_workers_per_gather;

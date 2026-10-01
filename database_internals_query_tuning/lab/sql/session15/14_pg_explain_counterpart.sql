-- S15-14 PostgreSQL で同じクエリの実行計画を読む（13 と見比べる）
-- MySQL と条件をそろえるため、InnoDB が外部キーに自動で作るのと同じインデックスも作る
CREATE INDEX IF NOT EXISTS orders_ordered_at_idx ON orders (ordered_at);
CREATE INDEX order_items_order_id_idx ON order_items (order_id);
CREATE INDEX orders_customer_id_idx ON orders (customer_id);
ANALYZE orders, order_items;

EXPLAIN (ANALYZE, BUFFERS)
SELECT c.region, count(DISTINCT o.id) AS orders, sum(oi.quantity * oi.unit_price) AS sales
FROM orders o
JOIN customers c ON c.id = o.customer_id
JOIN order_items oi ON oi.order_id = o.id
WHERE o.ordered_at >= '2025-06-01' AND o.ordered_at < '2025-06-08'
  AND o.status <> 'cancelled'
GROUP BY c.region
ORDER BY sales DESC;

SELECT c.region, count(DISTINCT o.id) AS orders, sum(oi.quantity * oi.unit_price) AS sales
FROM orders o
JOIN customers c ON c.id = o.customer_id
JOIN order_items oi ON oi.order_id = o.id
WHERE o.ordered_at >= '2025-06-01' AND o.ordered_at < '2025-06-08'
  AND o.status <> 'cancelled'
GROUP BY c.region
ORDER BY sales DESC;

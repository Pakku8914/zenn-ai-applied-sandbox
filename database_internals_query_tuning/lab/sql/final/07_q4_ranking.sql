-- Final-07 Q4 商品別ランキング（文具・直近 7 日の上位 10 商品）
EXPLAIN (ANALYZE, BUFFERS)
SELECT p.id, p.name, sum(oi.quantity) AS qty, sum(oi.quantity * oi.unit_price) AS sales
FROM orders o
JOIN order_items oi ON oi.order_id = o.id
JOIN products p ON p.id = oi.product_id
WHERE o.ordered_at >= '2025-12-25' AND o.ordered_at < '2026-01-01'
  AND o.status <> 'cancelled' AND p.category = '文具'
GROUP BY p.id, p.name
ORDER BY sales DESC
LIMIT 10;

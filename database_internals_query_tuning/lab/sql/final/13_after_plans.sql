-- Final-13 改善後の 5 本の計画（10・12 の後。Q2 は 14 の短いトランザクションの UPDATE）
-- Q1 顧客の注文一覧
EXPLAIN (ANALYZE, BUFFERS)
SELECT o.id, o.ordered_at, o.status, count(*) AS items, sum(oi.quantity * oi.unit_price) AS amount
FROM orders o JOIN order_items oi ON oi.order_id = o.id
WHERE o.customer_id = 12345
GROUP BY o.id
ORDER BY o.ordered_at DESC
LIMIT 10;

-- Q2 在庫引き当て（改善後の 1 文。ROLLBACK するので在庫は変わらない）
BEGIN;
EXPLAIN (ANALYZE, BUFFERS)
UPDATE final_products SET stock = stock - 1 WHERE id = 777 AND stock >= 1 RETURNING stock;
ROLLBACK;

-- Q3 未発送の注文の検索
EXPLAIN (ANALYZE, BUFFERS)
SELECT order_id, customer_id, ordered_at
FROM final_ship_queue
WHERE region = '東京'
ORDER BY ordered_at
LIMIT 50;

-- Q4 商品別ランキング
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

-- Q5 日別の売上（インデックスを足しても計画は変わらない）
EXPLAIN (ANALYZE, BUFFERS)
SELECT date_trunc('day', o.ordered_at) AS day,
       count(DISTINCT o.customer_id) AS buyers,
       sum(oi.quantity * oi.unit_price) AS sales
FROM orders o JOIN order_items oi ON oi.order_id = o.id
WHERE o.status <> 'cancelled'
  AND o.ordered_at >= '2025-10-03' AND o.ordered_at < '2026-01-01'
GROUP BY 1
ORDER BY 1;

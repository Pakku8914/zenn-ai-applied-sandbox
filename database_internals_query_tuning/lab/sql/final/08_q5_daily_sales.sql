-- Final-08 Q5 日別の売上（直近 90 日の日別売上と購入者数）：1 回あたりは 5 本の中でいちばん遅い
EXPLAIN (ANALYZE, BUFFERS)
SELECT date_trunc('day', o.ordered_at) AS day,
       count(DISTINCT o.customer_id) AS buyers,
       sum(oi.quantity * oi.unit_price) AS sales
FROM orders o JOIN order_items oi ON oi.order_id = o.id
WHERE o.status <> 'cancelled'
  AND o.ordered_at >= '2025-10-03' AND o.ordered_at < '2026-01-01'
GROUP BY 1
ORDER BY 1;

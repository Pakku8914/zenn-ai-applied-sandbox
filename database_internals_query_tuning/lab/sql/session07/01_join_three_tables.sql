-- S07-01 出発点での 3 テーブル結合：「2025年3月1日〜7日に売れた『文具』の売上」
-- 先に出発点へ戻しておく: docker compose exec lab bash tools/reset.sh
-- 売上は status <> 'cancelled' の注文だけで数える（全章共通のルール）

-- (1) 既定のまま実行する。PostgreSQL 18 は並列（Gather → Parallel ...）を選びやすい
EXPLAIN (ANALYZE, BUFFERS)
SELECT sum(oi.quantity * oi.unit_price) AS sales, count(*) AS lines
FROM orders o
JOIN order_items oi ON oi.order_id = o.id
JOIN products p ON p.id = oi.product_id
WHERE o.ordered_at >= '2025-03-01' AND o.ordered_at < '2025-03-08'
  AND o.status <> 'cancelled'
  AND p.category = '文具';

-- (2) 結合方式の比較に集中するため、この章では並列を切って読む（このセッションの中だけ有効）
SET max_parallel_workers_per_gather = 0;

EXPLAIN (ANALYZE, BUFFERS)
SELECT sum(oi.quantity * oi.unit_price) AS sales, count(*) AS lines
FROM orders o
JOIN order_items oi ON oi.order_id = o.id
JOIN products p ON p.id = oi.product_id
WHERE o.ordered_at >= '2025-03-01' AND o.ordered_at < '2025-03-08'
  AND o.status <> 'cancelled'
  AND p.category = '文具';

-- (3) 結果そのもの（どの結合方式でも同じ値になることを後で確かめる）
SELECT sum(oi.quantity * oi.unit_price) AS sales, count(*) AS lines
FROM orders o
JOIN order_items oi ON oi.order_id = o.id
JOIN products p ON p.id = oi.product_id
WHERE o.ordered_at >= '2025-03-01' AND o.ordered_at < '2025-03-08'
  AND o.status <> 'cancelled'
  AND p.category = '文具';

RESET max_parallel_workers_per_gather;

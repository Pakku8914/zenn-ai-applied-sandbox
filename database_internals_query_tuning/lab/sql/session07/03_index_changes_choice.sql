-- S07-03 外部キー列 order_items.order_id にインデックスを作ると、選ばれる結合方式はどう変わるか
-- PostgreSQL は外部キー制約を付けても参照する側の列にインデックスを自動では作らない

CREATE INDEX order_items_order_id_idx ON order_items (order_id);

SET max_parallel_workers_per_gather = 0;

-- (1) 1 週間分：インデックスがあっても既定は Hash Join のまま
EXPLAIN (ANALYZE, BUFFERS)
SELECT sum(oi.quantity * oi.unit_price) AS sales, count(*) AS lines
FROM orders o
JOIN order_items oi ON oi.order_id = o.id
JOIN products p ON p.id = oi.product_id
WHERE o.ordered_at >= '2025-03-01' AND o.ordered_at < '2025-03-08'
  AND o.status <> 'cancelled'
  AND p.category = '文具';

-- (2) 同じ 1 週間分で Nested Loop だけを許す：内側が「インデックスで 1 注文ぶんを引く」形になる
SET enable_hashjoin = off;
SET enable_mergejoin = off;
EXPLAIN (ANALYZE, BUFFERS)
SELECT sum(oi.quantity * oi.unit_price) AS sales, count(*) AS lines
FROM orders o
JOIN order_items oi ON oi.order_id = o.id
JOIN products p ON p.id = oi.product_id
WHERE o.ordered_at >= '2025-03-01' AND o.ordered_at < '2025-03-08'
  AND o.status <> 'cancelled'
  AND p.category = '文具';
RESET enable_hashjoin;
RESET enable_mergejoin;

-- (3) 1 日分に絞る：外側が小さくなると、既定でも Nested Loop が選ばれる
EXPLAIN (ANALYZE, BUFFERS)
SELECT sum(oi.quantity * oi.unit_price) AS sales, count(*) AS lines
FROM orders o
JOIN order_items oi ON oi.order_id = o.id
JOIN products p ON p.id = oi.product_id
WHERE o.ordered_at >= '2025-03-01' AND o.ordered_at < '2025-03-02'
  AND o.status <> 'cancelled'
  AND p.category = '文具';

-- (4) 2 日分にすると（並列なしの場合）、orders と order_items の結合は Hash Join に戻る
EXPLAIN (COSTS OFF)
SELECT sum(oi.quantity * oi.unit_price) AS sales, count(*) AS lines
FROM orders o
JOIN order_items oi ON oi.order_id = o.id
JOIN products p ON p.id = oi.product_id
WHERE o.ordered_at >= '2025-03-01' AND o.ordered_at < '2025-03-03'
  AND o.status <> 'cancelled'
  AND p.category = '文具';

RESET max_parallel_workers_per_gather;

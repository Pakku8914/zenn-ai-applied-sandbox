-- S07 練習問題の模範解答：期間の長さで選ばれる結合方式を予測し、実測で確かめる
-- 前提：03 の order_items(order_id) と 05 の orders(ordered_at) のインデックスがある状態（無ければ作る）
CREATE INDEX IF NOT EXISTS order_items_order_id_idx ON order_items (order_id);
CREATE INDEX IF NOT EXISTS orders_ordered_at_idx ON orders (ordered_at);
SET max_parallel_workers_per_gather = 0;

-- (1) 1 日分：既定は Nested Loop
EXPLAIN (COSTS OFF)
SELECT sum(oi.quantity * oi.unit_price) FROM orders o JOIN order_items oi ON oi.order_id = o.id
WHERE o.ordered_at >= '2025-03-01' AND o.ordered_at < '2025-03-02' AND o.status <> 'cancelled';

-- (2) 2 日分：既定は Hash Join に切り替わる
EXPLAIN (COSTS OFF)
SELECT sum(oi.quantity * oi.unit_price) FROM orders o JOIN order_items oi ON oi.order_id = o.id
WHERE o.ordered_at >= '2025-03-01' AND o.ordered_at < '2025-03-03' AND o.status <> 'cancelled';

-- (3) 1 か月分を 2 方式で実測する：まず既定（Hash Join）
EXPLAIN (ANALYZE, TIMING OFF)
SELECT sum(oi.quantity * oi.unit_price) FROM orders o JOIN order_items oi ON oi.order_id = o.id
WHERE o.ordered_at >= '2025-03-01' AND o.ordered_at < '2025-04-01' AND o.status <> 'cancelled';

-- (4) 同じ 1 か月分を Nested Loop に限定して実測する
SET enable_hashjoin = off;
SET enable_mergejoin = off;
EXPLAIN (ANALYZE, TIMING OFF)
SELECT sum(oi.quantity * oi.unit_price) FROM orders o JOIN order_items oi ON oi.order_id = o.id
WHERE o.ordered_at >= '2025-03-01' AND o.ordered_at < '2025-04-01' AND o.status <> 'cancelled';

RESET enable_hashjoin;
RESET enable_mergejoin;
RESET max_parallel_workers_per_gather;

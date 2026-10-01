-- S07-02 enable_* で結合方式を 1 つに絞り、同じクエリを 3 方式で実行する（インデックスは主キーだけ）
-- enable_hashjoin などを off にしても「その方式を禁止」ではなく「他に方法が無いときだけ使う」扱いになる。
-- PostgreSQL 18 では、それでも使われたノードに Disabled: true と表示される（17 以前は巨大なコストを足していた）。
-- 他に手段がなければ off にした方式でも使われる。本番のチューニングに使う設定ではない（観察用）

SET max_parallel_workers_per_gather = 0;

-- (1) Nested Loop だけを許す
SET enable_hashjoin = off;
SET enable_mergejoin = off;
SET enable_nestloop = on;
EXPLAIN (ANALYZE, BUFFERS)
SELECT sum(oi.quantity * oi.unit_price) AS sales, count(*) AS lines
FROM orders o
JOIN order_items oi ON oi.order_id = o.id
JOIN products p ON p.id = oi.product_id
WHERE o.ordered_at >= '2025-03-01' AND o.ordered_at < '2025-03-08'
  AND o.status <> 'cancelled'
  AND p.category = '文具';

-- (2) Merge Join だけを許す
SET enable_hashjoin = off;
SET enable_mergejoin = on;
SET enable_nestloop = off;
EXPLAIN (ANALYZE, BUFFERS)
SELECT sum(oi.quantity * oi.unit_price) AS sales, count(*) AS lines
FROM orders o
JOIN order_items oi ON oi.order_id = o.id
JOIN products p ON p.id = oi.product_id
WHERE o.ordered_at >= '2025-03-01' AND o.ordered_at < '2025-03-08'
  AND o.status <> 'cancelled'
  AND p.category = '文具';

-- (3) Hash Join だけを許す（出発点の既定プランと同じ形になる）
SET enable_hashjoin = on;
SET enable_mergejoin = off;
SET enable_nestloop = off;
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
RESET enable_nestloop;
RESET max_parallel_workers_per_gather;

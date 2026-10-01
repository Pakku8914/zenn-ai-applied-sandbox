-- S15 演習：地域ごとの売上金額上位5商品（売上はキャンセル除外）— PostgreSQL
-- 先に出発点へ戻しておく: docker compose exec lab bash tools/reset.sh
-- ex02_regional_top5_mysql.sql と同じクエリ。計画の違いを「なぜ違うか」で説明する

-- (1) 結果（地域ごとに5行ずつ、25行）
WITH s AS (
  SELECT c.region, oi.product_id, sum(oi.quantity * oi.unit_price) AS sales
  FROM orders o
  JOIN customers c ON c.id = o.customer_id
  JOIN order_items oi ON oi.order_id = o.id
  WHERE o.status <> 'cancelled'
  GROUP BY c.region, oi.product_id
), r AS (
  SELECT region, product_id, sales,
         row_number() OVER (PARTITION BY region ORDER BY sales DESC, product_id) AS rn
  FROM s
)
SELECT region, rn, product_id, sales FROM r WHERE rn <= 5 ORDER BY region, rn;

-- (2) 既定の計画
EXPLAIN (ANALYZE, BUFFERS)
WITH s AS (
  SELECT c.region, oi.product_id, sum(oi.quantity * oi.unit_price) AS sales
  FROM orders o
  JOIN customers c ON c.id = o.customer_id
  JOIN order_items oi ON oi.order_id = o.id
  WHERE o.status <> 'cancelled'
  GROUP BY c.region, oi.product_id
), r AS (
  SELECT region, product_id, sales,
         row_number() OVER (PARTITION BY region ORDER BY sales DESC, product_id) AS rn
  FROM s
)
SELECT region, rn, product_id, sales FROM r WHERE rn <= 5 ORDER BY region, rn;

-- (3) 並列実行を止める（MySQL は1つのクエリを1つのスレッドで実行する）
SET max_parallel_workers_per_gather = 0;
EXPLAIN (ANALYZE, BUFFERS)
WITH s AS (
  SELECT c.region, oi.product_id, sum(oi.quantity * oi.unit_price) AS sales
  FROM orders o
  JOIN customers c ON c.id = o.customer_id
  JOIN order_items oi ON oi.order_id = o.id
  WHERE o.status <> 'cancelled'
  GROUP BY c.region, oi.product_id
), r AS (
  SELECT region, product_id, sales,
         row_number() OVER (PARTITION BY region ORDER BY sales DESC, product_id) AS rn
  FROM s
)
SELECT region, rn, product_id, sales FROM r WHERE rn <= 5 ORDER BY region, rn;

-- (4) MySQL と同じ形（外部キーのインデックスを引く Nested Loop）を強制する。
--     InnoDB が自動で作る外部キーのインデックスと同じものを作ってから、Hash Join と Merge Join を止める
CREATE INDEX orders_customer_id_idx ON orders (customer_id);
CREATE INDEX order_items_order_id_idx ON order_items (order_id);
SET enable_hashjoin = off;
SET enable_mergejoin = off;
EXPLAIN (ANALYZE, BUFFERS)
WITH s AS (
  SELECT c.region, oi.product_id, sum(oi.quantity * oi.unit_price) AS sales
  FROM orders o
  JOIN customers c ON c.id = o.customer_id
  JOIN order_items oi ON oi.order_id = o.id
  WHERE o.status <> 'cancelled'
  GROUP BY c.region, oi.product_id
), r AS (
  SELECT region, product_id, sales,
         row_number() OVER (PARTITION BY region ORDER BY sales DESC, product_id) AS rn
  FROM s
)
SELECT region, rn, product_id, sales FROM r WHERE rn <= 5 ORDER BY region, rn;
RESET ALL;

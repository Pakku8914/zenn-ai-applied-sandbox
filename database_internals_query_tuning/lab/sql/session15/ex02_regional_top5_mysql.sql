-- S15 演習：地域ごとの売上金額上位5商品（売上はキャンセル除外）— MySQL
-- docker compose exec -T lab mysql --skip-ssl -h mysql -ulab shopdb -t < sql/session15/ex02_regional_top5_mysql.sql
-- 先に出発点へ戻しておく（インデックスは主キーと外部キー用のものだけ）

-- (1) 結果（地域ごとに5行ずつ、25行）
WITH s AS (
  SELECT c.region, oi.product_id, SUM(oi.quantity * oi.unit_price) AS sales
  FROM orders o
  JOIN customers c ON c.id = o.customer_id
  JOIN order_items oi ON oi.order_id = o.id
  WHERE o.status <> 'cancelled'
  GROUP BY c.region, oi.product_id
), r AS (
  SELECT region, product_id, sales,
         ROW_NUMBER() OVER (PARTITION BY region ORDER BY sales DESC, product_id) AS rn
  FROM s
)
SELECT region, rn, product_id, sales FROM r WHERE rn <= 5 ORDER BY region, rn;

-- (2) 既定の計画：外部キーのインデックスを引く Nested Loop
EXPLAIN ANALYZE
WITH s AS (
  SELECT c.region, oi.product_id, SUM(oi.quantity * oi.unit_price) AS sales
  FROM orders o
  JOIN customers c ON c.id = o.customer_id
  JOIN order_items oi ON oi.order_id = o.id
  WHERE o.status <> 'cancelled'
  GROUP BY c.region, oi.product_id
), r AS (
  SELECT region, product_id, sales,
         ROW_NUMBER() OVER (PARTITION BY region ORDER BY sales DESC, product_id) AS rn
  FROM s
)
SELECT region, rn, product_id, sales FROM r WHERE rn <= 5 ORDER BY region, rn\G

-- (3) 使えるインデックスが無いときだけ Hash Join になる。結合に使える索引を IGNORE INDEX で外して確かめる
EXPLAIN ANALYZE
WITH s AS (
  SELECT c.region, oi.product_id, SUM(oi.quantity * oi.unit_price) AS sales
  FROM orders o IGNORE INDEX (PRIMARY, fk_orders_customer)
  JOIN customers c IGNORE INDEX (PRIMARY) ON c.id = o.customer_id
  JOIN order_items oi IGNORE INDEX (fk_items_order) ON oi.order_id = o.id
  WHERE o.status <> 'cancelled'
  GROUP BY c.region, oi.product_id
), r AS (
  SELECT region, product_id, sales,
         ROW_NUMBER() OVER (PARTITION BY region ORDER BY sales DESC, product_id) AS rn
  FROM s
)
SELECT region, rn, product_id, sales FROM r WHERE rn <= 5 ORDER BY region, rn\G

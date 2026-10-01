-- S07 練習問題の模範解答：統計が前日のままの作業用テーブル。直し方は「インデックス」か「ANALYZE」か
-- 06 と同じ作業用テーブルを作り直す（06 を実行済みでも最初からやり直す）
DROP TABLE IF EXISTS s07_stage_items, s07_stage_orders;
CREATE TABLE s07_stage_orders (
    batch_date date NOT NULL, order_id bigint NOT NULL, customer_id integer NOT NULL, status text NOT NULL
) WITH (autovacuum_enabled = false);
CREATE TABLE s07_stage_items (
    batch_date date NOT NULL, order_id bigint NOT NULL, product_id integer NOT NULL,
    quantity integer NOT NULL, unit_price integer NOT NULL
) WITH (autovacuum_enabled = false);
INSERT INTO s07_stage_orders
SELECT ordered_at::date, id, customer_id, status FROM orders
WHERE ordered_at >= '2025-12-30' AND ordered_at < '2025-12-31';
INSERT INTO s07_stage_items
SELECT o.ordered_at::date, oi.order_id, oi.product_id, oi.quantity, oi.unit_price
FROM order_items oi JOIN orders o ON o.id = oi.order_id
WHERE o.ordered_at >= '2025-12-30' AND o.ordered_at < '2025-12-31';
ANALYZE s07_stage_orders, s07_stage_items;
INSERT INTO s07_stage_orders
SELECT ordered_at::date, id, customer_id, status FROM orders
WHERE ordered_at >= '2025-12-31' AND ordered_at < '2026-01-01';
INSERT INTO s07_stage_items
SELECT o.ordered_at::date, oi.order_id, oi.product_id, oi.quantity, oi.unit_price
FROM order_items oi JOIN orders o ON o.id = oi.order_id
WHERE o.ordered_at >= '2025-12-31' AND o.ordered_at < '2026-01-01';

-- (1) 案A：統計はそのままで、内側の結合キーにインデックスを作る
CREATE INDEX s07_stage_items_order_id_idx ON s07_stage_items (order_id);
EXPLAIN (ANALYZE, BUFFERS)
SELECT sum(i.quantity * i.unit_price) AS sales, count(*) AS lines
FROM s07_stage_orders o
JOIN s07_stage_items i ON i.order_id = o.order_id
WHERE o.batch_date = '2025-12-31' AND i.batch_date = '2025-12-31'
  AND o.status <> 'cancelled';

-- (2) 案B：インデックスを消し、統計を取り直す
DROP INDEX s07_stage_items_order_id_idx;
ANALYZE s07_stage_orders, s07_stage_items;
EXPLAIN (ANALYZE, BUFFERS)
SELECT sum(i.quantity * i.unit_price) AS sales, count(*) AS lines
FROM s07_stage_orders o
JOIN s07_stage_items i ON i.order_id = o.order_id
WHERE o.batch_date = '2025-12-31' AND i.batch_date = '2025-12-31'
  AND o.status <> 'cancelled';

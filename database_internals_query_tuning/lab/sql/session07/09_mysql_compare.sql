-- S07-09 MySQL ではどうなるか（mysql クライアントで実行する）
-- docker compose exec lab mysql --skip-ssl -h mysql -ulab shopdb
-- mysql> source sql/session07/09_mysql_compare.sql
-- InnoDB は外部キー制約を付けると参照する側の列にインデックスを自動で作る（order_items の fk_items_order / fk_items_product）

-- (1) 同じ 3 テーブル結合：外部キーのインデックスを引く Nested Loop になる
SHOW INDEX FROM order_items;
EXPLAIN ANALYZE
SELECT SUM(oi.quantity * oi.unit_price) AS sales, COUNT(*) AS `lines`
FROM orders o
JOIN order_items oi ON oi.order_id = o.id
JOIN products p ON p.id = oi.product_id
WHERE o.ordered_at >= '2025-03-01' AND o.ordered_at < '2025-03-08'
  AND o.status <> 'cancelled'
  AND p.category = '文具'\G

-- (2) インデックスの無い等値結合は Hash Join になる（MySQL 8.0.18 で導入、8.0.20 以降は Block Nested Loop を置き換えた）
DROP TABLE IF EXISTS s07_stage_items, s07_stage_orders;
CREATE TABLE s07_stage_orders (
    batch_date DATE NOT NULL, order_id BIGINT NOT NULL, customer_id INT NOT NULL, status VARCHAR(10) NOT NULL
);
CREATE TABLE s07_stage_items (
    batch_date DATE NOT NULL, order_id BIGINT NOT NULL, product_id INT NOT NULL,
    quantity INT NOT NULL, unit_price INT NOT NULL
);
INSERT INTO s07_stage_orders
SELECT DATE(ordered_at), id, customer_id, status FROM orders
WHERE ordered_at >= '2025-12-30' AND ordered_at < '2026-01-01';
INSERT INTO s07_stage_items
SELECT DATE(o.ordered_at), oi.order_id, oi.product_id, oi.quantity, oi.unit_price
FROM order_items oi JOIN orders o ON o.id = oi.order_id
WHERE o.ordered_at >= '2025-12-30' AND o.ordered_at < '2026-01-01';

EXPLAIN ANALYZE
SELECT SUM(i.quantity * i.unit_price) AS sales, COUNT(*) AS `lines`
FROM s07_stage_orders o
JOIN s07_stage_items i ON i.order_id = o.order_id
WHERE o.batch_date = '2025-12-31' AND i.batch_date = '2025-12-31'
  AND o.status <> 'cancelled'\G

SELECT SUM(i.quantity * i.unit_price) AS sales, COUNT(*) AS `lines`
FROM s07_stage_orders o
JOIN s07_stage_items i ON i.order_id = o.order_id
WHERE o.batch_date = '2025-12-31' AND i.batch_date = '2025-12-31'
  AND o.status <> 'cancelled';

DROP TABLE s07_stage_items, s07_stage_orders;

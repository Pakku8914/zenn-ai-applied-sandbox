-- S07-04 外側が小さく、内側をインデックスで引ける：Nested Loop が最速になる典型
-- 「注文 1 件（id = 500000）の明細と商品名」。03 で作った order_items_order_id_idx を使う

-- (1) 既定：Nested Loop が 2 段になる
EXPLAIN (ANALYZE, BUFFERS)
SELECT o.id AS order_id, o.ordered_at, p.name, oi.quantity, oi.unit_price
FROM orders o
JOIN order_items oi ON oi.order_id = o.id
JOIN products p ON p.id = oi.product_id
WHERE o.id = 500000;

-- (2) 比較用：Nested Loop を禁止すると、products（5,000 行）を全部読んでハッシュ表を作ることになる
SET enable_nestloop = off;
EXPLAIN (ANALYZE, BUFFERS)
SELECT o.id AS order_id, o.ordered_at, p.name, oi.quantity, oi.unit_price
FROM orders o
JOIN order_items oi ON oi.order_id = o.id
JOIN products p ON p.id = oi.product_id
WHERE o.id = 500000;
RESET enable_nestloop;

-- (3) 比較用：order_items(order_id) のインデックスが無かったら？
-- DROP INDEX をトランザクションの中で行い、ROLLBACK で元に戻す。
-- この間 order_items は排他ロックで他のセッションから読み書きできなくなる（本番では絶対にやらない）
BEGIN;
DROP INDEX order_items_order_id_idx;
EXPLAIN (ANALYZE, BUFFERS)
SELECT o.id AS order_id, o.ordered_at, p.name, oi.quantity, oi.unit_price
FROM orders o
JOIN order_items oi ON oi.order_id = o.id
JOIN products p ON p.id = oi.product_id
WHERE o.id = 500000;
ROLLBACK;

-- (4) 結果
SELECT o.id AS order_id, o.ordered_at, p.name, oi.quantity, oi.unit_price
FROM orders o
JOIN order_items oi ON oi.order_id = o.id
JOIN products p ON p.id = oi.product_id
WHERE o.id = 500000
ORDER BY oi.id;

-- Mid01-11 MySQL ではどうなるか（mysql クライアントで実行する）
-- docker compose exec lab mysql --skip-ssl -h mysql -ulab shopdb
-- mysql> source sql/mid01/11_mysql_compare.sql
-- orders(customer_id) には外部キー用のインデックス fk_orders_customer が最初からある（InnoDB が自動で作る）
CREATE INDEX customers_email_idx ON customers (email);
CREATE INDEX orders_ordered_at_idx ON orders (ordered_at);

-- (1) クエリ A：照合順序 utf8mb4_0900_ai_ci は大文字・小文字を区別しない。lower() を掛けなくても一致する
SELECT COUNT(*) AS orders
FROM customers c JOIN orders o ON o.customer_id = c.id
WHERE c.email = 'User12345@Example.com';

EXPLAIN ANALYZE
SELECT o.id, o.ordered_at, o.status
FROM customers c JOIN orders o ON o.customer_id = c.id
WHERE c.email = 'User12345@Example.com'
ORDER BY o.ordered_at DESC\G

-- (2) クエリ A を lower() で書くと、MySQL でもインデックスは使われない
EXPLAIN ANALYZE
SELECT o.id, o.ordered_at, o.status
FROM customers c JOIN orders o ON o.customer_id = c.id
WHERE lower(c.email) = lower('User12345@Example.com')
ORDER BY o.ordered_at DESC\G

-- (3) クエリ B：同じ取り込みテーブルを作る（昨夜分で ANALYZE → TRUNCATE → 今夜分）
DROP TABLE IF EXISTS mid01_import;
CREATE TABLE mid01_import (
  batch_date DATE NOT NULL, order_id BIGINT NOT NULL, line_no INT NOT NULL,
  product_id INT NOT NULL, quantity INT NOT NULL, unit_price INT NOT NULL
) ENGINE=InnoDB;
INSERT INTO mid01_import
SELECT DATE(o.ordered_at), oi.order_id, ROW_NUMBER() OVER (PARTITION BY oi.order_id ORDER BY oi.id),
       oi.product_id, oi.quantity, oi.unit_price
FROM order_items oi JOIN orders o ON o.id = oi.order_id
WHERE o.ordered_at >= '2025-12-30' AND o.ordered_at < '2025-12-31';
ANALYZE TABLE mid01_import;
TRUNCATE TABLE mid01_import;
INSERT INTO mid01_import
SELECT DATE(o.ordered_at), oi.order_id, ROW_NUMBER() OVER (PARTITION BY oi.order_id ORDER BY oi.id),
       oi.product_id, oi.quantity, oi.unit_price
FROM order_items oi JOIN orders o ON o.id = oi.order_id
WHERE o.ordered_at >= '2025-12-31' AND o.ordered_at < '2026-01-01';
INSERT INTO mid01_import
SELECT batch_date, order_id, line_no + 10, product_id, quantity, unit_price
FROM mid01_import
WHERE line_no = 1 AND order_id IN (SELECT order_id FROM (SELECT DISTINCT order_id FROM mid01_import ORDER BY order_id LIMIT 3) x);

EXPLAIN ANALYZE
SELECT COUNT(*) AS dup_lines
FROM mid01_import a
JOIN mid01_import b
  ON b.order_id = a.order_id AND b.product_id = a.product_id AND b.line_no > a.line_no
WHERE a.batch_date = '2025-12-31' AND b.batch_date = '2025-12-31'\G

-- (4) クエリ C：row_number() で 20 件を取る書き方と ORDER BY ... LIMIT の書き方
EXPLAIN ANALYZE
SELECT id, customer_id, ordered_at
FROM (
  SELECT id, customer_id, ordered_at, ROW_NUMBER() OVER (ORDER BY ordered_at DESC) AS rn
  FROM orders WHERE status = 'pending'
) t
WHERE rn <= 20
ORDER BY rn\G

EXPLAIN ANALYZE
SELECT id, customer_id, ordered_at
FROM orders
WHERE status = 'pending'
ORDER BY ordered_at DESC
LIMIT 20\G

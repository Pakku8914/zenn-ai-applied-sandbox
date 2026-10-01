-- S09-10 MySQL ではどうなるか（mysql クライアントで実行する）
-- docker compose exec lab mysql --skip-ssl -h mysql -ulab shopdb
-- mysql> source sql/session09/10_mysql_compare.sql
-- orders(customer_id) には外部キー用のインデックス fk_orders_customer が最初からある（InnoDB が自動で作る）

-- (1) InnoDB のセカンダリインデックスは主キーの値を持つ：id と customer_id だけならインデックスだけで返せる
EXPLAIN ANALYZE SELECT id, customer_id FROM orders WHERE customer_id = 12345\G
-- ordered_at を足すと、主キーでクラスタ化インデックス（行本体）を引きに行く
EXPLAIN ANALYZE SELECT id, ordered_at FROM orders WHERE customer_id = 12345\G

-- (2) 関数インデックス（MySQL 8.0.13 以降）：式を二重のかっこで書く
CREATE INDEX customers_lower_email_idx ON customers ((lower(email)));
EXPLAIN ANALYZE SELECT id FROM customers WHERE lower(email) = lower('User12345@Example.com')\G

-- (3) スキップスキャン（MySQL 8.0.13 以降）：先頭列 status を条件に含まないクエリ
CREATE INDEX orders_status_ordered_at_idx ON orders (status, ordered_at);
EXPLAIN ANALYZE
SELECT count(*) FROM orders WHERE ordered_at >= '2025-06-01' AND ordered_at < '2025-06-02'\G
-- インデックスに無い列（customer_id）を返すと、スキップスキャンは使われない（全件読み）
EXPLAIN ANALYZE
SELECT id, customer_id FROM orders WHERE ordered_at >= '2025-06-01' AND ordered_at < '2025-06-02'\G

-- 後片付け
DROP INDEX customers_lower_email_idx ON customers;
DROP INDEX orders_status_ordered_at_idx ON orders;

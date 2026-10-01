-- MySQL（InnoDB）での比較。mysql クライアントで実行する:
--   docker compose exec -T lab mysql --skip-ssl -h mysql -ulab shopdb -t < sql/session05/11_mysql_access_types.sql
CREATE INDEX customers_region_idx ON customers (region);
CREATE INDEX orders_ordered_at_idx ON orders (ordered_at);

-- (1) type 列: const / ref / range / ALL / index
EXPLAIN FORMAT=TRADITIONAL SELECT * FROM customers WHERE id = 12345;
EXPLAIN FORMAT=TRADITIONAL SELECT * FROM customers WHERE region = '東京';
EXPLAIN FORMAT=TRADITIONAL SELECT * FROM orders
WHERE ordered_at >= '2025-06-01' AND ordered_at < '2025-06-02';
EXPLAIN FORMAT=TRADITIONAL SELECT * FROM products WHERE category = '文具';
EXPLAIN FORMAT=TRADITIONAL SELECT count(*) FROM customers;

-- (2) セカンダリインデックスは主キーの値を持つので、id だけを取るならカバリングになる（Using index）
EXPLAIN FORMAT=TRADITIONAL SELECT id FROM customers WHERE region = '東京';

-- (3) 件数だけなら Covering index range scan（Visibility Map に相当するものはない）
EXPLAIN ANALYZE SELECT count(*) FROM orders
WHERE ordered_at >= '2025-06-01' AND ordered_at < '2025-06-02'\G

-- (4) 全列を取ると、セカンダリインデックスで見つけた主キーでクラスタ化インデックスを引き直す
EXPLAIN ANALYZE SELECT * FROM orders
WHERE ordered_at >= '2025-06-01' AND ordered_at < '2025-06-02'\G

-- (5) InnoDB は外部キーに自動でインデックスを作る（PostgreSQL は作らない。10_parallel_scan.sql の (1) と比べる）
EXPLAIN FORMAT=TRADITIONAL SELECT count(*) FROM orders WHERE customer_id = 777;

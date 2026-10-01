-- 練習（模範解答・応用）: 統計が古いとき、VACUUM では見積もりが直らないことを確かめる。
CREATE TABLE s06_orders WITH (autovacuum_enabled = false) AS SELECT * FROM orders;
CREATE INDEX s06_orders_status_idx ON s06_orders (status);
ANALYZE s06_orders;
INSERT INTO s06_orders (id, customer_id, ordered_at, status)
SELECT id + 1000000, customer_id, ordered_at + interval '1 year', 'returned'
FROM orders WHERE id % 4 = 0;

-- VACUUM は reltuples（行数）を更新するが、列の統計（MCV・ヒストグラム）は作り直さない
VACUUM s06_orders;
SELECT reltuples FROM pg_class WHERE relname = 's06_orders';
SELECT most_common_vals FROM pg_stats WHERE tablename = 's06_orders' AND attname = 'status';
EXPLAIN SELECT o.id, c.region FROM s06_orders o JOIN customers c ON c.id = o.customer_id
WHERE o.status = 'returned';

-- ANALYZE で直る（VACUUM (ANALYZE) なら両方を一度に行う）
ANALYZE s06_orders;
EXPLAIN SELECT o.id, c.region FROM s06_orders o JOIN customers c ON c.id = o.customer_id
WHERE o.status = 'returned';

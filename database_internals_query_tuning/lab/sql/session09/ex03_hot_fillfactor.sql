-- S09-ex03 HOT 更新とページの空き：fillfactor 100（既定）と 90 で同じ UPDATE を比べる
-- 出発点から実行する。どちらも customer_id にだけインデックスがあり、更新するのはインデックスの無い status

DROP TABLE IF EXISTS s09_ff100, s09_ff90;
CREATE TABLE s09_ff100 (LIKE orders) WITH (fillfactor = 100, autovacuum_enabled = false);
CREATE TABLE s09_ff90  (LIKE orders) WITH (fillfactor = 90,  autovacuum_enabled = false);
INSERT INTO s09_ff100 SELECT * FROM orders WHERE id <= 100000;
INSERT INTO s09_ff90  SELECT * FROM orders WHERE id <= 100000;
CREATE INDEX s09_ff100_customer_id_idx ON s09_ff100 (customer_id);
CREATE INDEX s09_ff90_customer_id_idx  ON s09_ff90 (customer_id);
VACUUM (ANALYZE) s09_ff100, s09_ff90;
SELECT relname, pg_relation_size(oid) / 8192 AS pages
FROM pg_class WHERE relname IN ('s09_ff100', 's09_ff90') ORDER BY relname;

SELECT pg_stat_reset_single_table_counters(oid) FROM pg_class WHERE relname IN ('s09_ff100', 's09_ff90');
UPDATE s09_ff100 SET status = CASE WHEN status = 'completed' THEN 'pending' ELSE 'completed' END WHERE id % 10 = 0;
UPDATE s09_ff90  SET status = CASE WHEN status = 'completed' THEN 'pending' ELSE 'completed' END WHERE id % 10 = 0;
SELECT pg_stat_force_next_flush();
SELECT pg_sleep(1);
SELECT relname, n_tup_upd, n_tup_hot_upd
FROM pg_stat_user_tables
WHERE relname IN ('s09_ff100', 's09_ff90')
ORDER BY relname;
SELECT relname, pg_relation_size(oid) / 8192 AS pages_after_update
FROM pg_class WHERE relname IN ('s09_ff100', 's09_ff90') ORDER BY relname;
SELECT relname, pg_size_pretty(pg_relation_size(oid)) AS index_size
FROM pg_class WHERE relname IN ('s09_ff100_customer_id_idx', 's09_ff90_customer_id_idx') ORDER BY relname;

-- 後片付け
DROP TABLE s09_ff100, s09_ff90;

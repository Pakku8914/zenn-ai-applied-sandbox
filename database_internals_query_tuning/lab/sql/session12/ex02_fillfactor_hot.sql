-- S12 演習: 一部の行だけを繰り返し更新する表では、fillfactor で空きを残すと HOT 更新になり、インデックスが太らない
-- \i sql/session12/ex02_fillfactor_hot.sql（数秒で終わる）
-- orders の先頭 20 万行を、fillfactor 100（既定）と 90 の2通りでコピーし、5% の行の status を書き換える
SET client_min_messages = warning;
DROP TABLE IF EXISTS s12_ff100, s12_ff90;
RESET client_min_messages;
CREATE TABLE s12_ff100 (LIKE orders) WITH (autovacuum_enabled = off);
CREATE TABLE s12_ff90 (LIKE orders) WITH (autovacuum_enabled = off, fillfactor = 90);
INSERT INTO s12_ff100 SELECT * FROM orders WHERE id <= 200000 ORDER BY id;
INSERT INTO s12_ff90 SELECT * FROM orders WHERE id <= 200000 ORDER BY id;
ALTER TABLE s12_ff100 ADD PRIMARY KEY (id);
ALTER TABLE s12_ff90 ADD PRIMARY KEY (id);
VACUUM (ANALYZE) s12_ff100, s12_ff90;
SELECT c.relname, pg_relation_size(c.oid) / 8192 AS heap_pages,
       pg_relation_size(c.relname || '_pkey') / 8192 AS pkey_pages, i.avg_leaf_density
FROM pg_class AS c, LATERAL pgstatindex(c.relname || '_pkey') AS i
WHERE c.relname IN ('s12_ff100', 's12_ff90') ORDER BY c.relname;

UPDATE s12_ff100 SET status = 'pending' WHERE id % 20 = 0;
UPDATE s12_ff90 SET status = 'pending' WHERE id % 20 = 0;

-- HOT 更新の数と、テーブル・インデックスのページ数（統計は少し遅れて反映されるので、先に反映を促す）
SELECT pg_stat_force_next_flush();
SELECT relname, n_tup_upd, n_tup_hot_upd FROM pg_stat_user_tables WHERE relname IN ('s12_ff100', 's12_ff90') ORDER BY relname;
SELECT c.relname, pg_relation_size(c.oid) / 8192 AS heap_pages,
       pg_relation_size(c.relname || '_pkey') / 8192 AS pkey_pages, i.avg_leaf_density
FROM pg_class AS c, LATERAL pgstatindex(c.relname || '_pkey') AS i
WHERE c.relname IN ('s12_ff100', 's12_ff90') ORDER BY c.relname;

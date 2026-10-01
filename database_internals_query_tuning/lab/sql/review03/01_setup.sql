-- R03-01 横断復習③の作業用コピー r03_orders（100万行）を作る（何度実行してもよい。数秒で終わる）
-- \i sql/review03/01_setup.sql
-- 4テーブルの行は変えない。自動の VACUUM / ANALYZE に先回りされないよう autovacuum_enabled = off で作る
SET client_min_messages = warning;
DROP TABLE IF EXISTS r03_orders, r03_customers;
RESET client_min_messages;
CREATE TABLE r03_orders (LIKE orders) WITH (autovacuum_enabled = off);
INSERT INTO r03_orders SELECT * FROM orders ORDER BY id;
SELECT pg_stat_force_next_flush();
ALTER TABLE r03_orders ADD PRIMARY KEY (id);
VACUUM (ANALYZE) r03_orders;
SELECT pg_relation_size('r03_orders') / 8192 AS heap_pages, relfilenode FROM pg_class WHERE relname = 'r03_orders';

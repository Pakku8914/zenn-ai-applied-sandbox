-- S13 演習2 INSERT ... SELECT と COPY の WAL を、レコードの種類ごとに比べる（なぜ COPY の WAL は少ないのか）
-- \i sql/session13/ex02_copy_wal_stats.sql（04 で作った /tmp/s13_orders.csv を使う。無ければ作り直す）
CREATE EXTENSION IF NOT EXISTS pg_walinspect;
\copy (SELECT * FROM orders WHERE id <= 100000 ORDER BY id) TO '/tmp/s13_orders.csv' WITH (FORMAT csv)
SET client_min_messages = warning;
DROP TABLE IF EXISTS s13_ins, s13_copy;
RESET client_min_messages;
CREATE TABLE s13_ins (LIKE orders) WITH (autovacuum_enabled = off);
CREATE TABLE s13_copy (LIKE orders) WITH (autovacuum_enabled = off);

-- (1) INSERT ... SELECT
SELECT pg_current_wal_insert_lsn() AS lsn0 \gset
INSERT INTO s13_ins SELECT * FROM orders WHERE id <= 100000 ORDER BY id;
SELECT pg_current_wal_insert_lsn() AS lsn1 \gset
SELECT "resource_manager/record_type" AS record_type, count, record_size, fpi_size
FROM pg_get_wal_stats(:'lsn0', :'lsn1', true) WHERE count > 0 ORDER BY count DESC;

-- (2) COPY
SELECT pg_current_wal_insert_lsn() AS lsn0 \gset
\copy s13_copy FROM '/tmp/s13_orders.csv' WITH (FORMAT csv)
SELECT pg_current_wal_insert_lsn() AS lsn1 \gset
SELECT "resource_manager/record_type" AS record_type, count, record_size, fpi_size
FROM pg_get_wal_stats(:'lsn0', :'lsn1', true) WHERE count > 0 ORDER BY count DESC;

-- (3) どちらも同じ 10 万行。COPY のテーブルは末尾に空のページが付く（まとめてページを確保するため）
SELECT 's13_ins' AS t, count(*) AS rows, count(DISTINCT (ctid::text::point)[0]) AS used_pages,
       pg_relation_size('s13_ins') / 8192 AS pages FROM s13_ins
UNION ALL
SELECT 's13_copy', count(*), count(DISTINCT (ctid::text::point)[0]), pg_relation_size('s13_copy') / 8192 FROM s13_copy
ORDER BY t;

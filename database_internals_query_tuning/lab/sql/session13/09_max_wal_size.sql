-- S13-09 WAL の量でもチェックポイントは起きる：max_wal_size を小さくすると、チェックポイントが頻発し FPI で WAL が膨らむ
-- \i sql/session13/09_max_wal_size.sql（08 の (1) と同じ投入を 2 回。全体で 10 秒ほど）
-- ALTER SYSTEM で一時的に変える。最後に必ず RESET する（戻し忘れても tools/reset.sh が戻す）
SET client_min_messages = warning;
DROP TABLE IF EXISTS s13_first;
RESET client_min_messages;
CREATE TABLE s13_first (LIKE orders) WITH (autovacuum_enabled = off);
ALTER TABLE s13_first ADD PRIMARY KEY (id);
CREATE INDEX s13_first_customer_id_idx ON s13_first (customer_id);
CREATE INDEX s13_first_ordered_at_idx ON s13_first (ordered_at);

-- (1) 既定の max_wal_size（1GB）で 08 の (1) と同じ投入
SHOW max_wal_size;
CHECKPOINT;
SELECT num_timed, num_requested FROM pg_stat_checkpointer \gset c0_
\i sql/session13/wal_meter_start.sql
INSERT INTO s13_first SELECT * FROM orders ORDER BY id;
\i sql/session13/wal_meter_stop.sql
SELECT pg_sleep(1);
SELECT num_timed - :c0_num_timed AS timed, num_requested - :c0_num_requested AS requested FROM pg_stat_checkpointer;

-- (2) max_wal_size を 32MB（下限は WAL ファイル 2 つ分）にして、同じ投入をもう一度
TRUNCATE s13_first;
ALTER SYSTEM SET max_wal_size = '32MB';
SELECT pg_reload_conf();
SELECT pg_sleep(0.5);
SHOW max_wal_size;
CHECKPOINT;
SELECT num_timed, num_requested FROM pg_stat_checkpointer \gset c0_
\i sql/session13/wal_meter_start.sql
INSERT INTO s13_first SELECT * FROM orders ORDER BY id;
\i sql/session13/wal_meter_stop.sql
SELECT pg_sleep(1);
SELECT num_timed - :c0_num_timed AS timed, num_requested - :c0_num_requested AS requested FROM pg_stat_checkpointer;

-- 元に戻す
ALTER SYSTEM RESET max_wal_size;
SELECT pg_reload_conf();
SELECT pg_sleep(0.5);
SHOW max_wal_size;

-- S13-02 1 行の INSERT が WAL に何を書くかを、pg_walinspect で中身まで見る
-- \i sql/session13/02_wal_records.sql
CREATE EXTENSION IF NOT EXISTS pg_walinspect;
SET client_min_messages = warning;
DROP TABLE IF EXISTS s13_t;
RESET client_min_messages;
-- 主キー付きの小さな作業用テーブル（100 行）
CREATE TABLE s13_t (id int PRIMARY KEY, note text) WITH (autovacuum_enabled = off);
INSERT INTO s13_t SELECT g, 'row ' || g FROM generate_series(1, 100) AS g;

-- (1) 1 行を INSERT してコミットする前後の WAL の位置を取り、その間のレコードを並べる
SELECT pg_current_wal_insert_lsn() AS lsn0 \gset
BEGIN;
INSERT INTO s13_t VALUES (101, 'hello');
COMMIT;
SELECT pg_current_wal_insert_lsn() AS lsn1 \gset
SELECT start_lsn, xid, resource_manager, record_type, record_length, fpi_length, description
FROM pg_get_wal_records_info(:'lsn0', :'lsn1');

-- (2) EXPLAIN (ANALYZE, WAL) は、その文が作った WAL のレコード数・FPI 数・バイト数を表示する
--     （コミットのレコードは文の外で書かれるので数に入らない）
EXPLAIN (ANALYZE, WAL, COSTS OFF) INSERT INTO s13_t VALUES (102, 'world');

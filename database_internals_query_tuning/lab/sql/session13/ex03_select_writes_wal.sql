-- S13 演習3 SELECT しかしていないのに WAL が出る：チェックポイント直後に、投入したばかりの行を初めて読む
-- \i sql/session13/ex03_select_writes_wal.sql
-- PostgreSQL 18 は既定でデータチェックサムが有効（data_checksums = on）。行に「コミット済み」の印（ヒントビット）を
-- 付けるのもページの変更なので、チェックポイント後の最初の変更としてページの写し（FPI_FOR_HINT）が WAL に書かれる
SHOW data_checksums;
CREATE EXTENSION IF NOT EXISTS pg_walinspect;
SET client_min_messages = warning;
DROP TABLE IF EXISTS s13_hint;
RESET client_min_messages;
CREATE TABLE s13_hint (LIKE orders) WITH (autovacuum_enabled = off);
INSERT INTO s13_hint SELECT * FROM orders WHERE id <= 100000 ORDER BY id;
CHECKPOINT;

-- (1) 1 回目の SELECT：全ページにヒントビットを付ける（dirtied）＝ WAL に FPI が出る
SELECT pg_current_wal_insert_lsn() AS lsn0 \gset
EXPLAIN (ANALYZE, BUFFERS, WAL, COSTS OFF) SELECT count(*) FROM s13_hint;
SELECT pg_current_wal_insert_lsn() AS lsn1 \gset
-- SELECT にはコミットの fsync が無いので、この WAL はまだディスクに書かれていない（pg_walinspect はディスク上の WAL しか読めない）。
-- WAL writer が書き出すまで少し待つ
SELECT pg_sleep(1);
SELECT "resource_manager/record_type" AS record_type, count, record_size, fpi_size
FROM pg_get_wal_stats(:'lsn0', :'lsn1', true) WHERE count > 0 ORDER BY count DESC;

-- (2) 2 回目の SELECT：印は付いているので、ページも WAL も変わらない
EXPLAIN (ANALYZE, BUFFERS, WAL, COSTS OFF) SELECT count(*) FROM s13_hint;

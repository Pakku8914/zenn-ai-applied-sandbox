-- S13-06 チェックポイントが書き出すもの（pg_stat_checkpointer）と、チェックポイント直後に WAL が膨らむ理由（full page image）
-- \i sql/session13/06_checkpoint_fpi.sql
-- 作業用テーブル s13_fpi：orders の先頭 10 万行。fillfactor 90 でページに 1 割の空きを残し、UPDATE した行が同じページに収まるようにする
SET client_min_messages = warning;
DROP TABLE IF EXISTS s13_fpi;
RESET client_min_messages;
CREATE EXTENSION IF NOT EXISTS pg_walinspect;
CREATE TABLE s13_fpi (LIKE orders) WITH (fillfactor = 90, autovacuum_enabled = off);
INSERT INTO s13_fpi SELECT * FROM orders WHERE id <= 100000 ORDER BY id;
-- 投入直後の行に印（ヒントビット）を付け終えておく（S14 で扱う。付いていないと最初に読んだときにも FPI が出る）
VACUUM s13_fpi;
-- 下の (2)〜(4) と同じ UPDATE を一度だけ実行しておく。2 回目以降の UPDATE は、前回の UPDATE が残した古い版を
-- ページの中で片付ける処理（S12 で見た HOT の掃除）も行うので、(2)〜(4) の条件をそろえるため
UPDATE s13_fpi SET status = status WHERE id % 100 = 0;
SELECT pg_relation_size('s13_fpi') / 8192 AS pages;

-- (1) チェックポイントの前後で、チェックポイント処理の累計を比べる
--     num_requested … CHECKPOINT コマンドや WAL の量で「要求された」回数 / num_timed … checkpoint_timeout による回数
--     buffers_written … データファイルへ書き出したページ数
SHOW checkpoint_timeout;
SHOW max_wal_size;
SELECT num_timed, num_requested, num_done, buffers_written FROM pg_stat_checkpointer \gset c0_
CHECKPOINT;
SELECT num_timed - :c0_num_timed AS timed, num_requested - :c0_num_requested AS requested,
       num_done - :c0_num_done AS done, buffers_written - :c0_buffers_written AS buffers_written
FROM pg_stat_checkpointer;

-- (2) チェックポイント直後の UPDATE：1,000 行（100 行に 1 行）。ほぼすべてのページを 1 回ずつ変更する
SELECT pg_current_wal_insert_lsn() AS lsn0 \gset
EXPLAIN (ANALYZE, BUFFERS, WAL, COSTS OFF)
UPDATE s13_fpi SET status = status WHERE id % 100 = 0;
SELECT pg_current_wal_insert_lsn() AS lsn1 \gset
-- (2) が書いた WAL をレコードの種類ごとに集計する（fpi_size がページの写しのバイト数）
SELECT "resource_manager/record_type" AS record_type, count, record_size, fpi_size
FROM pg_get_wal_stats(:'lsn0', :'lsn1', true) WHERE count > 0 ORDER BY count DESC;

-- (3) 同じ UPDATE をもう一度（チェックポイントを挟まない）
SELECT pg_current_wal_insert_lsn() AS lsn0 \gset
EXPLAIN (ANALYZE, BUFFERS, WAL, COSTS OFF)
UPDATE s13_fpi SET status = status WHERE id % 100 = 0;
SELECT pg_current_wal_insert_lsn() AS lsn1 \gset
SELECT "resource_manager/record_type" AS record_type, count, record_size, fpi_size
FROM pg_get_wal_stats(:'lsn0', :'lsn1', true) WHERE count > 0 ORDER BY count DESC;

-- (4) チェックポイントを挟んでもう一度。また FPI が出る
CHECKPOINT;
EXPLAIN (ANALYZE, BUFFERS, WAL, COSTS OFF)
UPDATE s13_fpi SET status = status WHERE id % 100 = 0;

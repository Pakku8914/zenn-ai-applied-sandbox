-- S13-07 full_page_writes = off にすると FPI が出なくなる（実験のためだけに一時的に変える。本番では切らない）
-- \i sql/session13/07_full_page_writes.sql（06 の s13_fpi を使う）
-- ALTER SYSTEM はサーバー全体の設定を postgresql.auto.conf に書き込む。最後に必ず RESET して元に戻す
-- （戻し忘れても tools/reset.sh が ALTER SYSTEM RESET ALL で戻す）
ALTER SYSTEM SET full_page_writes = off;
SELECT pg_reload_conf();
SELECT pg_sleep(0.5);
SHOW full_page_writes;

-- チェックポイント直後の UPDATE（06 の (2) と同じ）。FPI が出ない
CHECKPOINT;
SELECT pg_current_wal_insert_lsn() AS lsn0 \gset
EXPLAIN (ANALYZE, BUFFERS, WAL, COSTS OFF)
UPDATE s13_fpi SET status = status WHERE id % 100 = 0;
SELECT pg_current_wal_insert_lsn() AS lsn1 \gset
SELECT "resource_manager/record_type" AS record_type, count, record_size, fpi_size
FROM pg_get_wal_stats(:'lsn0', :'lsn1', true) WHERE count > 0 ORDER BY count DESC;

-- 元に戻す
ALTER SYSTEM RESET full_page_writes;
SELECT pg_reload_conf();
SELECT pg_sleep(0.5);
SHOW full_page_writes;
SELECT name, setting, source FROM pg_settings WHERE name = 'full_page_writes';

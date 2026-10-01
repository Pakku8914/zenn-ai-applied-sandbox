-- S13 計測の終了：wal_meter_start.sql からの経過時間・WAL の量・レコード数・FPI 数・このセッションの fsync 回数と時間
--   wal_bytes … WAL の書き込み位置（LSN）がどれだけ進んだか（他のセッションの WAL も含む）
--   records / fpi … このセッションが作った WAL レコードの数と、そのうちページ丸ごとの写し（full page image）の数
--   fsyncs / fsync_ms … このセッションが WAL を fsync した回数と時間（コミット時の待ち）
SELECT round(extract(epoch FROM clock_timestamp() - :'m_t0'::timestamptz) * 1000) AS elapsed_ms,
       pg_size_pretty(pg_wal_lsn_diff(pg_current_wal_insert_lsn(), :'m_lsn0')) AS wal_bytes \gset m_
SELECT pg_stat_force_next_flush() \g /dev/null
SELECT :m_elapsed_ms AS elapsed_ms,
       :'m_wal_bytes' AS wal_bytes,
       w.wal_records - :m_rec0 AS records,
       w.wal_fpi - :m_fpi0 AS fpi,
       (SELECT sum(fsyncs) FROM pg_stat_get_backend_io(pg_backend_pid()) WHERE object = 'wal') - :m_fs0 AS fsyncs,
       round(((SELECT sum(fsync_time) FROM pg_stat_get_backend_io(pg_backend_pid()) WHERE object = 'wal') - :m_fst0)::numeric) AS fsync_ms
FROM pg_stat_get_backend_wal(pg_backend_pid()) AS w;

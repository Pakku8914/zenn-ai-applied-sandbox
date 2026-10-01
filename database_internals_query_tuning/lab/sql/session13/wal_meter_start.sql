-- S13 計測の開始：このセッション（接続）が出した WAL と fsync の回数を数え始める（\i sql/session13/wal_meter_start.sql）
-- 終わったら \i sql/session13/wal_meter_stop.sql で差分を表示する
-- fsync にかかった時間も数えるため、WAL の I/O 時間の計測をこのセッションだけ有効にする（スーパーユーザーだけが変えられる設定）
SET track_wal_io_timing = on;
SELECT pg_stat_force_next_flush() \g /dev/null
SELECT pg_current_wal_insert_lsn() AS m_lsn0,
       clock_timestamp() AS m_t0,
       w.wal_records AS m_rec0, w.wal_fpi AS m_fpi0,
       (SELECT sum(fsyncs) FROM pg_stat_get_backend_io(pg_backend_pid()) WHERE object = 'wal') AS m_fs0,
       (SELECT sum(fsync_time) FROM pg_stat_get_backend_io(pg_backend_pid()) WHERE object = 'wal') AS m_fst0
FROM pg_stat_get_backend_wal(pg_backend_pid()) AS w \gset

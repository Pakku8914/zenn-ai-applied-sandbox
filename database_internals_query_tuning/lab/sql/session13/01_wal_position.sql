-- S13-01 WAL（先行書き込みログ）の現在位置と、WAL ファイルの名前・大きさを見る
-- \i sql/session13/01_wal_position.sql
SHOW wal_level;
SHOW wal_segment_size;
-- LSN（Log Sequence Number）は WAL の中のバイト位置。「上位 32 ビット / 下位 32 ビット」を 16 進で表す
-- pg_walfile_name はその位置を含む WAL ファイル（16MB ずつのセグメント）の名前
SELECT pg_current_wal_lsn() AS lsn, pg_walfile_name(pg_current_wal_lsn()) AS walfile;
-- pg_wal ディレクトリの中身（新しい順に 3 つ）。どのファイルも 16MB
SELECT name, size FROM pg_ls_waldir() ORDER BY name DESC LIMIT 3;
-- サーバー起動（または統計のリセット）以降に書かれた WAL の累計
SELECT wal_records, wal_fpi, pg_size_pretty(wal_bytes) AS wal_bytes, stats_reset FROM pg_stat_wal;

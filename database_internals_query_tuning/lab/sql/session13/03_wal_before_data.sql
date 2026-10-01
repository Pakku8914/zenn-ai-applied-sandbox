-- S13-03 「WAL が先、データファイルは後」を、ページの LSN で確かめる
-- \i sql/session13/03_wal_before_data.sql（02 の s13_t を使う）
-- ページの先頭（ページヘッダ）には「このページを最後に変更した WAL レコードの位置（LSN）」が入っている
--   buffer … 共有バッファ上のページ（get_raw_page はバッファを通して読む）
--   file   … データファイル上のページ（pg_read_binary_file でファイルの先頭 8KB を直接読む）

-- (1) チェックポイント直後：メモリとファイルのページは同じ
CHECKPOINT;
SELECT (SELECT lsn FROM page_header(get_raw_page('s13_t', 0))) AS buffer_page_lsn,
       (SELECT lsn FROM page_header(pg_read_binary_file(pg_relation_filepath('s13_t'), 0, 8192))) AS file_page_lsn,
       pg_current_wal_flush_lsn() AS wal_flushed_upto;

-- (2) 1 行を UPDATE してコミット：メモリ上のページと WAL（ディスクまで fsync 済み）は進むが、データファイルのページは古いまま
SELECT pg_current_wal_insert_lsn() AS lsn0 \gset
UPDATE s13_t SET note = 'updated' WHERE id = 1;
SELECT pg_current_wal_insert_lsn() AS lsn1 \gset
SELECT (SELECT lsn FROM page_header(get_raw_page('s13_t', 0))) AS buffer_page_lsn,
       (SELECT lsn FROM page_header(pg_read_binary_file(pg_relation_filepath('s13_t'), 0, 8192))) AS file_page_lsn,
       pg_current_wal_flush_lsn() AS wal_flushed_upto;

-- この UPDATE が書いた WAL レコード。チェックポイント後の最初の変更なので、ページ丸ごとの写し（FPI）が付く（fpi_length）
SELECT start_lsn, resource_manager, record_type, record_length, fpi_length
FROM pg_get_wal_records_info(:'lsn0', :'lsn1');

-- (3) もう一度チェックポイント：変更済みのページ（ダーティページ）がデータファイルへ書き出され、両者がそろう
CHECKPOINT;
SELECT (SELECT lsn FROM page_header(get_raw_page('s13_t', 0))) AS buffer_page_lsn,
       (SELECT lsn FROM page_header(pg_read_binary_file(pg_relation_filepath('s13_t'), 0, 8192))) AS file_page_lsn,
       pg_current_wal_flush_lsn() AS wal_flushed_upto;

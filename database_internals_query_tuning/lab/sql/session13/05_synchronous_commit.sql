-- S13-05 synchronous_commit = off：コミットが WAL の fsync を待たなくなる。何が速くなり、何を失うのか
-- \i sql/session13/05_synchronous_commit.sql（(a') は 04 の (a) と同じ 10 万回の自動コミット。数秒かかる）
SHOW synchronous_commit;
SHOW wal_writer_delay;
SET client_min_messages = warning;
DROP TABLE IF EXISTS s13_aoff, s13_one;
RESET client_min_messages;
CREATE TABLE s13_aoff (LIKE orders) WITH (autovacuum_enabled = off);
CREATE TABLE s13_one (id int, note text) WITH (autovacuum_enabled = off);

-- (a') 04 の (a) と同じ 10 万回の自動コミットを、このセッションだけ synchronous_commit = off にして実行する
\echo '(a'') 1 行ずつ自動コミット（synchronous_commit = off）'
SET synchronous_commit = off;
-- fsync を代わりに行う WAL writer プロセスの fsync 回数（サーバー全体の累計）も前後で見る
SELECT fsyncs AS walwriter_fsyncs0 FROM pg_stat_io WHERE backend_type = 'walwriter' AND object = 'wal' AND context = 'normal' \gset
\i sql/session13/wal_meter_start.sql
\set QUIET on
SELECT format('INSERT INTO s13_aoff VALUES (%s, %s, %L, %L)', id, customer_id, ordered_at, status)
FROM orders WHERE id <= 100000 ORDER BY id \gexec
\set QUIET off
\i sql/session13/wal_meter_stop.sql
SELECT fsyncs - :walwriter_fsyncs0 AS walwriter_fsyncs FROM pg_stat_io WHERE backend_type = 'walwriter' AND object = 'wal' AND context = 'normal';
RESET synchronous_commit;

-- (1) 既定（on）：コミットが返った時点で、WAL はディスクまで書かれている
--     insert_lsn … WAL を書き込んだ位置（メモリ上の WAL バッファを含む）
--     flush_lsn  … ディスクへの fsync が済んだ位置。unflushed_bytes が 0 なら、自分のコミットまで永続化済み
INSERT INTO s13_one VALUES (1, 'synchronous_commit = on');
SELECT pg_current_wal_insert_lsn() AS insert_lsn, pg_current_wal_flush_lsn() AS flush_lsn,
       pg_wal_lsn_diff(pg_current_wal_insert_lsn(), pg_current_wal_flush_lsn()) AS unflushed_bytes;

-- (2) off：コミットは「WAL バッファに書いた」時点で返る。fsync は WAL writer が後でまとめて行う
SET synchronous_commit = off;
INSERT INTO s13_one VALUES (2, 'synchronous_commit = off');
SELECT pg_current_wal_insert_lsn() AS insert_lsn, pg_current_wal_flush_lsn() AS flush_lsn,
       pg_wal_lsn_diff(pg_current_wal_insert_lsn(), pg_current_wal_flush_lsn()) AS unflushed_bytes;
-- 1 秒待つと、WAL writer（wal_writer_delay ごとに起きる）が fsync を済ませている
SELECT pg_sleep(1);
SELECT pg_current_wal_insert_lsn() AS insert_lsn, pg_current_wal_flush_lsn() AS flush_lsn,
       pg_wal_lsn_diff(pg_current_wal_insert_lsn(), pg_current_wal_flush_lsn()) AS unflushed_bytes;
RESET synchronous_commit;

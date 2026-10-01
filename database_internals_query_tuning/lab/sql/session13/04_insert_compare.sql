-- S13-04 同じ 10 万行を (a) 1 行ずつ自動コミット (b) 1 トランザクション (c) COPY で入れ、時間・WAL の量・fsync の回数を比べる
-- \i sql/session13/04_insert_compare.sql（(a) は 1 行ごとにコミットするので 10 秒ほどかかる）
-- 入れる行は orders の先頭 10 万行。作業用テーブルはインデックスなし・自動 VACUUM なし（計測に VACUUM の WAL を混ぜない）
SET client_min_messages = warning;
DROP TABLE IF EXISTS s13_a, s13_b, s13_b2, s13_c;
RESET client_min_messages;
CREATE TABLE s13_a  (LIKE orders) WITH (autovacuum_enabled = off);
CREATE TABLE s13_b  (LIKE orders) WITH (autovacuum_enabled = off);
CREATE TABLE s13_b2 (LIKE orders) WITH (autovacuum_enabled = off);
CREATE TABLE s13_c  (LIKE orders) WITH (autovacuum_enabled = off);
-- COPY 用の CSV を lab コンテナの /tmp に書き出しておく（\copy は psql 側のファイルを読み書きする）
\copy (SELECT * FROM orders WHERE id <= 100000 ORDER BY id) TO '/tmp/s13_orders.csv' WITH (FORMAT csv)

-- (a) 1 行ずつの INSERT を 10 万回。psql の自動コミットなので、1 文ごとに 1 トランザクション＝1 回のコミット
--     \gexec は、SELECT が返した文字列を 1 行ずつ SQL として実行する。10 万行の「INSERT 0 1」を出さないよう QUIET にする
\echo '(a) 1 行ずつ自動コミット'
\i sql/session13/wal_meter_start.sql
\set QUIET on
SELECT format('INSERT INTO s13_a VALUES (%s, %s, %L, %L)', id, customer_id, ordered_at, status)
FROM orders WHERE id <= 100000 ORDER BY id \gexec
\set QUIET off
\i sql/session13/wal_meter_stop.sql

-- (b) 同じ 10 万回の INSERT を BEGIN と COMMIT で囲む。文の数は (a) と同じで、コミットだけが 1 回になる
\echo '(b) 1 トランザクション'
\i sql/session13/wal_meter_start.sql
\set QUIET on
BEGIN;
SELECT format('INSERT INTO s13_b VALUES (%s, %s, %L, %L)', id, customer_id, ordered_at, status)
FROM orders WHERE id <= 100000 ORDER BY id \gexec
COMMIT;
\set QUIET off
\i sql/session13/wal_meter_stop.sql

-- (b2) 参考：1 文の INSERT ... SELECT（サーバーの中で 10 万行を作るので、往復も 1 回）
\echo '(b2) INSERT ... SELECT（1 文）'
\i sql/session13/wal_meter_start.sql
INSERT INTO s13_b2 SELECT * FROM orders WHERE id <= 100000 ORDER BY id;
\i sql/session13/wal_meter_stop.sql

-- (c) COPY（psql の \copy）。ファイルの中身をまとめて送り、ページ単位で複数行をまとめて書く
\echo '(c) COPY'
\i sql/session13/wal_meter_start.sql
\copy s13_c FROM '/tmp/s13_orders.csv' WITH (FORMAT csv)
\i sql/session13/wal_meter_stop.sql

-- 4 つとも同じ 10 万行・同じページ数になったことを確かめる
SELECT 's13_a' AS t, count(*) AS rows, pg_relation_size('s13_a') / 8192 AS pages FROM s13_a
UNION ALL SELECT 's13_b', count(*), pg_relation_size('s13_b') / 8192 FROM s13_b
UNION ALL SELECT 's13_b2', count(*), pg_relation_size('s13_b2') / 8192 FROM s13_b2
UNION ALL SELECT 's13_c', count(*), pg_relation_size('s13_c') / 8192 FROM s13_c
ORDER BY t;

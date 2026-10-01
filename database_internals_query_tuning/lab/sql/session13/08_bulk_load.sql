-- S13-08 一括投入を速くする方法：インデックスを後から作る・UNLOGGED テーブル。それぞれの時間と WAL の量と代償
-- \i sql/session13/08_bulk_load.sql（orders の 100 万行を入れる。全体で 10 秒ほど）
-- 途中で WAL の量によるチェックポイントが走ると FPI が混ざるので、計測の前ごとに CHECKPOINT しておく
SET client_min_messages = warning;
DROP TABLE IF EXISTS s13_first, s13_after, s13_unlogged;
RESET client_min_messages;

-- (1) インデックス（主キー＋2 つ）を先に作ってから 100 万行を入れる。1 行ごとに 3 つの B+木へ差し込む
CREATE TABLE s13_first (LIKE orders) WITH (autovacuum_enabled = off);
ALTER TABLE s13_first ADD PRIMARY KEY (id);
CREATE INDEX s13_first_customer_id_idx ON s13_first (customer_id);
CREATE INDEX s13_first_ordered_at_idx ON s13_first (ordered_at);
CHECKPOINT;
\echo '(1) インデックスを先に作ってから INSERT'
\i sql/session13/wal_meter_start.sql
INSERT INTO s13_first SELECT * FROM orders ORDER BY id;
\i sql/session13/wal_meter_stop.sql

-- (2) インデックスなしで入れてから、3 つのインデックスを作る（(2a) と (2b) の合計が (1) と同じ結果になる）
CREATE TABLE s13_after (LIKE orders) WITH (autovacuum_enabled = off);
CHECKPOINT;
\echo '(2a) インデックスなしで INSERT'
\i sql/session13/wal_meter_start.sql
INSERT INTO s13_after SELECT * FROM orders ORDER BY id;
\i sql/session13/wal_meter_stop.sql
\echo '(2b) 後からインデックスを 3 つ作る'
\i sql/session13/wal_meter_start.sql
ALTER TABLE s13_after ADD PRIMARY KEY (id);
CREATE INDEX s13_after_customer_id_idx ON s13_after (customer_id);
CREATE INDEX s13_after_ordered_at_idx ON s13_after (ordered_at);
\i sql/session13/wal_meter_stop.sql

-- (3) UNLOGGED テーブル：WAL を書かない。代わりにクラッシュ後の起動でテーブルが空になる
CREATE UNLOGGED TABLE s13_unlogged (LIKE orders) WITH (autovacuum_enabled = off);
CHECKPOINT;
\echo '(3) UNLOGGED テーブルに INSERT'
\i sql/session13/wal_meter_start.sql
INSERT INTO s13_unlogged SELECT * FROM orders ORDER BY id;
\i sql/session13/wal_meter_stop.sql

-- (4) UNLOGGED テーブルには「初期化フォーク」（ファイル名の末尾が _init の空ファイル）がある。
--     クラッシュ後の起動時、PostgreSQL は本体をこの空のファイルで置き換える（WAL が無いので中身を復元できないから）
SELECT relname, relpersistence FROM pg_class WHERE relname IN ('s13_after', 's13_unlogged') ORDER BY relname;
SELECT pg_relation_filepath('s13_unlogged') AS path,
       (pg_stat_file(pg_relation_filepath('s13_unlogged'))).size AS main_size,
       (pg_stat_file(pg_relation_filepath('s13_unlogged') || '_init')).size AS init_fork_size;

-- (5) 入れ終わってから SET LOGGED にすると、テーブル全体を WAL に書く（後払い）
CHECKPOINT;
\echo '(5) ALTER TABLE ... SET LOGGED'
\i sql/session13/wal_meter_start.sql
ALTER TABLE s13_unlogged SET LOGGED;
\i sql/session13/wal_meter_stop.sql
SELECT relname, relpersistence FROM pg_class WHERE relname = 's13_unlogged';

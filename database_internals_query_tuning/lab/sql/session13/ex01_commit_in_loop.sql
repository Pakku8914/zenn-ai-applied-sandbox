-- S13 演習1 サーバーの中のループで 10 万行を入れ、「1 行ごとにコミット」と「最後に 1 回だけコミット」を比べる
-- \i sql/session13/ex01_commit_in_loop.sql
-- psql との往復（04 の (a)(b) では 10 万回）を取り除き、コミットの回数だけを変える。
-- DO ブロックはトランザクションの外で実行すれば、中で COMMIT できる（後に何も残らない）
SET client_min_messages = warning;
DROP TABLE IF EXISTS s13_loop1, s13_loopn, s13_loopoff;
RESET client_min_messages;
CREATE TABLE s13_loop1 (LIKE orders) WITH (autovacuum_enabled = off);
CREATE TABLE s13_loopn (LIKE orders) WITH (autovacuum_enabled = off);
CREATE TABLE s13_loopoff (LIKE orders) WITH (autovacuum_enabled = off);

\echo '(1) ループの中で 1 行ごとに COMMIT（10 万回）'
\i sql/session13/wal_meter_start.sql
DO $$
BEGIN
  FOR i IN 1..100000 LOOP
    INSERT INTO s13_loop1 SELECT * FROM orders WHERE id = i;
    COMMIT;
  END LOOP;
END $$;
\i sql/session13/wal_meter_stop.sql

\echo '(2) ループが終わってから 1 回だけ COMMIT'
\i sql/session13/wal_meter_start.sql
DO $$
BEGIN
  FOR i IN 1..100000 LOOP
    INSERT INTO s13_loopn SELECT * FROM orders WHERE id = i;
  END LOOP;
END $$;
\i sql/session13/wal_meter_stop.sql

\echo '(3) (1) を synchronous_commit = off で'
SET synchronous_commit = off;
\i sql/session13/wal_meter_start.sql
DO $$
BEGIN
  FOR i IN 1..100000 LOOP
    INSERT INTO s13_loopoff SELECT * FROM orders WHERE id = i;
    COMMIT;
  END LOOP;
END $$;
\i sql/session13/wal_meter_stop.sql
RESET synchronous_commit;

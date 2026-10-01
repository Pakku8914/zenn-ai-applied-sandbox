-- S15-10 PostgreSQL セッション A：スナップショットを持ったまま待つ（1つ目の端末）
-- docker compose exec lab psql -f sql/session15/10_pg_vacuum_session_a.sql
-- pg_sleep の 40 秒のあいだに、2つ目の端末で 11_pg_vacuum_session_b.sql を実行する。
-- 途中でやめるときは Ctrl+C のあと ROLLBACK;（psql を抜ければ ROLLBACK される）
BEGIN ISOLATION LEVEL REPEATABLE READ;
SELECT sum(v) FROM s15_mvcc;
SELECT pg_sleep(40) AS waiting_for_session_b;
SELECT sum(v) FROM s15_mvcc;
EXPLAIN (ANALYZE, BUFFERS) SELECT sum(v) FROM s15_mvcc;
COMMIT;

-- S15-11 PostgreSQL セッション B：A がスナップショットを持っている間に更新する（2つ目の端末）
-- docker compose exec lab psql -f sql/session15/11_pg_vacuum_session_b.sql

-- (1) id = 1 を 5000 回更新する（1 回ごとに COMMIT。DO の中の COMMIT は PostgreSQL 11 以降）
DO $$
BEGIN
  FOR i IN 1..5000 LOOP
    UPDATE s15_mvcc SET v = v + 1 WHERE id = 1;
    COMMIT;
  END LOOP;
END $$;

-- (2) 古い版はヒープに残る。新しい読み手も、増えたページを読み、版ごとに見えるかどうかを判定する
SELECT sum(v) FROM s15_mvcc;
SELECT pg_relation_size('s15_mvcc') / 8192 AS pages;
EXPLAIN (ANALYZE, BUFFERS) SELECT sum(v) FROM s15_mvcc;

-- (3) A のスナップショットが古い版を必要としているので、VACUUM は回収できない
VACUUM (VERBOSE) s15_mvcc;

-- (4) 回収を止めているトランザクションを探す（backend_xmin を持ち続けている接続）
SELECT pid <> pg_backend_pid() AS other_session, state, backend_xmin IS NOT NULL AS holds_xmin,
       now() - xact_start > interval '1 second' AS long_running, left(query, 40) AS query
FROM pg_stat_activity
WHERE datname = current_database() AND backend_xmin IS NOT NULL AND pid <> pg_backend_pid();

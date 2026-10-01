-- Final-02 どのクエリから直すか：pg_stat_statements を総実行時間（total_exec_time）の順に並べる
-- workload.py を実行した直後に実行する（workload.py は最初にこの DB の分だけ統計をリセットしている）
-- 自分でリセットするときは、この DB だけを指定する（引数なしの pg_stat_statements_reset() は全 DB の統計を消す）:
--   SELECT pg_stat_statements_reset(0, (SELECT oid FROM pg_database WHERE datname = current_database()), 0);
SELECT rank() OVER (ORDER BY total_exec_time DESC) AS rank,
       calls,
       round(total_exec_time::numeric, 0) AS total_ms,
       round((100 * total_exec_time / sum(total_exec_time) OVER ())::numeric, 1) AS pct,
       round(mean_exec_time::numeric, 2) AS mean_ms,
       round(max_exec_time::numeric, 1) AS max_ms,
       rows,
       left(regexp_replace(query, '\s+', ' ', 'g'), 52) AS query
FROM pg_stat_statements
WHERE dbid = (SELECT oid FROM pg_database WHERE datname = current_database())
  AND toplevel                                  -- EXPLAIN ANALYZE の中で実行された分（toplevel = false）は除く
  AND query NOT LIKE '%pg_stat_statements%'
ORDER BY total_exec_time DESC
LIMIT 10;

-- Final-04 Q2 在庫引き当て：1 回の計画は一瞬なのに、pg_stat_statements の平均と最大が大きい
-- workload.py を実行した直後に実行する

-- (1) 引き当ての最初の文の計画。主キーで 1 行を探してロックするだけ（ROLLBACK するので在庫は変わらない）
BEGIN;
EXPLAIN (ANALYZE, BUFFERS)
SELECT stock FROM final_products WHERE id = 777 FOR UPDATE;
ROLLBACK;

-- (2) 同じ文の pg_stat_statements。最小と最大の差、読んだページ数に注目する
SELECT calls,
       round(min_exec_time::numeric, 3) AS min_ms,
       round(mean_exec_time::numeric, 2) AS mean_ms,
       round(max_exec_time::numeric, 1) AS max_ms,
       round(stddev_exec_time::numeric, 1) AS stddev_ms,
       round(shared_blks_hit::numeric / calls, 1) AS pages_per_call
FROM pg_stat_statements
WHERE dbid = (SELECT oid FROM pg_database WHERE datname = current_database())
  AND toplevel
  AND query LIKE 'SELECT stock FROM final_products%';

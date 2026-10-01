-- S16-08 接続数とメモリ
-- 接続を確立するコストは src/session16/connection_cost.py で測る:
--   docker compose exec lab python src/session16/connection_cost.py

-- (1) 同時に張れる接続の上限と、接続ごと・ノードごとに確保されるメモリの設定
SELECT name, setting, unit FROM pg_settings
WHERE name IN ('max_connections', 'work_mem', 'hash_mem_multiplier', 'maintenance_work_mem', 'shared_buffers')
ORDER BY name;

-- (2) この接続（バックエンドプロセス）自身が今使っているメモリ
SELECT pg_size_pretty(sum(total_bytes)) AS this_backend_total,
       pg_size_pretty(sum(used_bytes)) AS this_backend_used
FROM pg_backend_memory_contexts;

-- (3) 最悪の見積もり：全接続が同時に、work_mem を使うノード（ソート・ハッシュ）を N 個持つクエリを実行したら
SELECT n_nodes,
       pg_size_pretty(current_setting('max_connections')::bigint * n_nodes
                      * pg_size_bytes(current_setting('work_mem'))) AS worst_case_work_mem
FROM (VALUES (1), (3)) AS t(n_nodes);

-- (4) このサンドボックスにはレプリカが無い（読み取りレプリカの話は本文だけで扱う）
SELECT pg_is_in_recovery() AS is_replica,
       (SELECT count(*) FROM pg_stat_replication) AS replicas;

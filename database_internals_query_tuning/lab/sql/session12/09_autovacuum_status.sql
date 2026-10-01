-- S12-09 autovacuum の状態を見る（何度でも実行してよい）: \i sql/session12/09_autovacuum_status.sql
-- n_dead_tup が「発火点」を超えると、autovacuum_naptime（このサンドボックスは 10 秒）以内に自動の VACUUM が走る
SELECT now()::time(0) AS now, n_live_tup, n_dead_tup, n_mod_since_analyze AS mod_since_analyze,
       last_autovacuum::time(0) AS last_autovacuum, autovacuum_count AS av_count,
       last_autoanalyze::time(0) AS last_autoanalyze, autoanalyze_count AS aa_count
FROM pg_stat_user_tables WHERE relname = 's12_orders';

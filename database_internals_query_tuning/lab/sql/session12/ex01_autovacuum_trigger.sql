-- S12 演習: 4テーブルそれぞれで、自動の VACUUM / ANALYZE が走るのは不要行・変更行が何行を超えたときか
-- \i sql/session12/ex01_autovacuum_trigger.sql
-- 発火点 = autovacuum_vacuum_threshold + autovacuum_vacuum_scale_factor × reltuples（PostgreSQL 18 は autovacuum_vacuum_max_threshold = 1億 で頭打ち）
SELECT c.relname, c.reltuples::bigint AS reltuples,
       least(current_setting('autovacuum_vacuum_threshold')::int
               + current_setting('autovacuum_vacuum_scale_factor')::float8 * c.reltuples,
             current_setting('autovacuum_vacuum_max_threshold')::float8) AS vacuum_trigger,
       current_setting('autovacuum_analyze_threshold')::int
         + current_setting('autovacuum_analyze_scale_factor')::float8 * c.reltuples AS analyze_trigger
FROM pg_class AS c
WHERE c.relname IN ('customers', 'products', 'orders', 'order_items')
ORDER BY c.reltuples;

-- R03-08 大量更新のあとの統計のずれ（S06 の復習）と、自動 ANALYZE の発火点（S12）
-- \i sql/review03/08_stats_after_bulk_update.sql（01 から作り直すので 20 秒ほど）
\i sql/review03/01_setup.sql
CREATE INDEX r03_orders_status_idx ON r03_orders (status);
ANALYZE r03_orders;

-- (1) 更新前：キャンセルは 43,478 件。見積もりと実測が合う
EXPLAIN (ANALYZE, BUFFERS)
SELECT count(*) FROM r03_orders WHERE status = 'cancelled';

-- (2) 5 件に 1 件をキャンセルにする一括更新（20万行）
UPDATE r03_orders SET status = 'cancelled' WHERE id % 5 = 0;
SELECT pg_stat_force_next_flush();
SELECT n_mod_since_analyze, n_dead_tup,
       current_setting('autovacuum_analyze_threshold')::int
         + current_setting('autovacuum_analyze_scale_factor')::float8 * c.reltuples AS analyze_trigger
FROM pg_stat_user_tables AS s JOIN pg_class AS c ON c.oid = s.relid
WHERE s.relname = 'r03_orders';

-- (3) 統計が古いまま：見積もりは 4 万件台のまま、実際は 23 万件
EXPLAIN (ANALYZE, BUFFERS)
SELECT count(*) FROM r03_orders WHERE status = 'cancelled';

-- (4) ANALYZE で統計を取り直すと、見積もりが実際に近づき、計画も変わる
ANALYZE r03_orders;
EXPLAIN (ANALYZE, BUFFERS)
SELECT count(*) FROM r03_orders WHERE status = 'cancelled';

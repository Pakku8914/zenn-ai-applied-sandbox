-- S14-09 メモリ設定の役割の違い：どれが実際にメモリを確保し、いつ・どこで変えられるか
-- \i sql/session14/09_memory_settings.sql
--   context … postmaster：再起動が必要 / user：SET でセッションごとに変えられる
SELECT name, setting, unit, context, short_desc
FROM pg_settings
WHERE name IN ('shared_buffers', 'work_mem', 'hash_mem_multiplier', 'maintenance_work_mem', 'effective_cache_size')
ORDER BY name;
-- shared_buffers はサーバー起動時に確保する共有メモリ。セッションの中では変えられない
SET shared_buffers = '512MB';
-- maintenance_work_mem は CREATE INDEX・VACUUM などの保守作業 1 回ごとに使う。値で CREATE INDEX の時間がどう変わるか
\timing on
SET maintenance_work_mem = '1MB';
CREATE INDEX s14_mwm_idx ON order_items (order_id);
DROP INDEX s14_mwm_idx;
SET maintenance_work_mem = '64MB';
CREATE INDEX s14_mwm_idx ON order_items (order_id);
DROP INDEX s14_mwm_idx;
SET maintenance_work_mem = '256MB';
CREATE INDEX s14_mwm_idx ON order_items (order_id);
DROP INDEX s14_mwm_idx;
\timing off
RESET maintenance_work_mem;

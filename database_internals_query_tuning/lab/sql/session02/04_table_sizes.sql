-- セッション2-4: 4 テーブルの大きさをページ数で見る
-- relpages / reltuples は VACUUM・ANALYZE が記録した値（pg_class）。pg_relation_size はファイルの実サイズ
SELECT c.relname,
       c.relpages,
       c.reltuples::bigint                                AS reltuples,
       pg_relation_size(c.oid)                            AS bytes,
       pg_size_pretty(pg_relation_size(c.oid))            AS size,
       pg_relation_size(c.oid) / 8192                     AS pages_by_size,
       round((c.reltuples / c.relpages)::numeric, 1)      AS rows_per_page
FROM pg_class c
WHERE c.relnamespace = 'public'::regnamespace
  AND c.relname IN ('customers', 'products', 'orders', 'order_items')
ORDER BY c.relpages;

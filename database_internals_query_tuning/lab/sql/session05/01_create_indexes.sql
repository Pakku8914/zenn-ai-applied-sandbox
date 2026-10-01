-- S05 の出発点: tools/reset.sh の直後（主キーと外部キーのみ）に実行する。
-- このセッションで使うインデックスを 2 本作る。
--   customers(region)   : 5 地域に均等分布（選択率 20%）
--   orders(ordered_at)  : 日付は id（物理的な並び順）と相関しない
CREATE INDEX customers_region_idx ON customers (region);
CREATE INDEX orders_ordered_at_idx ON orders (ordered_at);

-- 作ったインデックスの大きさ（ページ数）を確認する
SELECT c.relname AS index_name, c.relpages, pg_size_pretty(pg_relation_size(c.oid)) AS size
FROM pg_class c
WHERE c.relname IN ('customers_region_idx', 'orders_ordered_at_idx', 'customers_pkey', 'orders_pkey')
ORDER BY c.relname;

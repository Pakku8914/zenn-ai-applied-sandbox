-- セッション2-8: 小さなテーブル（products, 5,000 行）でも同じことが起きるか
-- products も 1 ページ目から順に満杯まで詰まっている
SELECT relpages, reltuples::bigint AS reltuples FROM pg_class WHERE relname = 'products';

SELECT 0 AS page, lower, upper, upper - lower AS free_bytes, (lower - 24) / 4 AS line_pointers
FROM page_header(get_raw_page('products', 0))
UNION ALL
SELECT 36, lower, upper, upper - lower, (lower - 24) / 4
FROM page_header(get_raw_page('products', 36));

BEGIN;
SELECT ctid, * FROM products WHERE id = 1;
UPDATE products SET stock = stock + 1 WHERE id = 1;
SELECT ctid, * FROM products WHERE id = 1;
SELECT lp, t_xmax, t_ctid FROM heap_page_items(get_raw_page('products', 0)) WHERE lp = 1;
SELECT n_tup_upd, n_tup_hot_upd FROM pg_stat_xact_user_tables WHERE relname = 'products';
ROLLBACK;

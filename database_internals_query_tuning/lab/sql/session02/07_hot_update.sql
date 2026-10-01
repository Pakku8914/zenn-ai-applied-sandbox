-- セッション2-7: ページに空きがあれば、新しい版は同じページに入る（HOT 更新）
-- orders の先頭 1 万行を 2 つの作業用テーブルに写す。違いは fillfactor（ページをどこまで詰めるか）だけ
--   s02_orders_ff100 : fillfactor 100（既定。ページを満杯まで詰める）
--   s02_orders_ff90  : fillfactor 90（各ページの 10% を更新用に空けておく）
DROP TABLE IF EXISTS s02_orders_ff100, s02_orders_ff90;
CREATE TABLE s02_orders_ff100 (LIKE orders INCLUDING ALL);
CREATE TABLE s02_orders_ff90  (LIKE orders INCLUDING ALL) WITH (fillfactor = 90);
INSERT INTO s02_orders_ff100 SELECT * FROM orders WHERE id <= 10000 ORDER BY id;
INSERT INTO s02_orders_ff90  SELECT * FROM orders WHERE id <= 10000 ORDER BY id;

-- 0 ページ目の空き領域と、テーブル全体のページ数
SELECT 's02_orders_ff100' AS tbl, lower, upper, upper - lower AS free_bytes, (lower - 24) / 4 AS line_pointers,
       pg_relation_size('s02_orders_ff100') / 8192 AS pages
FROM page_header(get_raw_page('s02_orders_ff100', 0))
UNION ALL
SELECT 's02_orders_ff90', lower, upper, upper - lower, (lower - 24) / 4,
       pg_relation_size('s02_orders_ff90') / 8192
FROM page_header(get_raw_page('s02_orders_ff90', 0));

-- fillfactor 100: 0 ページ目は満杯なので、新しい版は別のページ（空きのある最終ページ）へ
BEGIN;
UPDATE s02_orders_ff100 SET status = 'pending' WHERE id = 1;
SELECT ctid, * FROM s02_orders_ff100 WHERE id = 1;
SELECT lp, t_xmin, t_xmax, t_ctid, f.raw_flags
FROM heap_page_items(get_raw_page('s02_orders_ff100', 0)) AS h,
     LATERAL heap_tuple_infomask_flags(h.t_infomask, h.t_infomask2) AS f
WHERE lp = 1;
SELECT n_tup_upd, n_tup_hot_upd FROM pg_stat_xact_user_tables WHERE relname = 's02_orders_ff100';
ROLLBACK;

-- fillfactor 90: 0 ページ目に空きがあるので、新しい版は同じページの末尾（次の行ポインタ番号）へ
BEGIN;
UPDATE s02_orders_ff90 SET status = 'pending' WHERE id = 1;
SELECT ctid, * FROM s02_orders_ff90 WHERE id = 1;
-- 古い版（lp=1）と新しい版（最後の行ポインタ）。
-- 古い版に HEAP_HOT_UPDATED、新しい版に HEAP_ONLY_TUPLE が立つ（インデックスには新しい版の項目を足さない）
SELECT lp, t_xmin, t_xmax, t_ctid, f.raw_flags
FROM heap_page_items(get_raw_page('s02_orders_ff90', 0)) AS h,
     LATERAL heap_tuple_infomask_flags(h.t_infomask, h.t_infomask2) AS f
WHERE lp = 1
   OR lp = (SELECT max(lp) FROM heap_page_items(get_raw_page('s02_orders_ff90', 0)))
ORDER BY lp;
SELECT n_tup_upd, n_tup_hot_upd FROM pg_stat_xact_user_tables WHERE relname = 's02_orders_ff90';
ROLLBACK;

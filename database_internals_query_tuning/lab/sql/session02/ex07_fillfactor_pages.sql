-- 演習 S02-ex07: fillfactor を 90 にするとページ数はどれだけ増えるか（1 万行で比較）
-- 07_hot_update.sql を実行した後に実行する（s02_orders_ff100 / s02_orders_ff90 を使う）
-- 0 ページ目の行数は「見える行」で数える（07 で ROLLBACK した版もページには残っているため）
SELECT 's02_orders_ff100' AS tbl,
       pg_relation_size('s02_orders_ff100') / 8192 AS pages,
       (SELECT count(*) FROM s02_orders_ff100 WHERE ctid < '(1,0)') AS rows_on_page0
UNION ALL
SELECT 's02_orders_ff90',
       pg_relation_size('s02_orders_ff90') / 8192,
       (SELECT count(*) FROM s02_orders_ff90 WHERE ctid < '(1,0)');

-- fillfactor 90 は「ページの 10%（819 バイト）を空けた状態で次のページへ移る」。
-- 使えるのは 8192 - 819 - 24 = 7349 バイト → 7349 / 68 ≒ 108 行（実際は短い pending 行が混じるので 109 行）
SELECT floor((8192 - 8192 * 0.10 - 24) / 68) AS rows_per_page_est,
       ceil(10000 / 109.0)                    AS est_pages_with_109;

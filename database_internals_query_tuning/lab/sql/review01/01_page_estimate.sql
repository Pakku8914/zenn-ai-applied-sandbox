-- 横断復習①: S02 のページ数見積もりを customers と order_items で再出題する。
-- 前提: tools/reset.sh の直後
-- 見積もりの式: 1 ページに入る行数 = (8192 − ページヘッダ 24) ÷ (タプルの長さを 8 の倍数に切り上げたもの + 行ポインタ 4)

-- (1) 1 行（タプル）の長さ: 0 ページ目の行ポインタが指す長さ lp_len
SELECT 'customers' AS テーブル, count(*) AS 行数, min(lp_len), max(lp_len)
FROM heap_page_items(get_raw_page('customers', 0))
UNION ALL
SELECT 'customers（最終ページ）', count(*), min(lp_len), max(lp_len)
FROM heap_page_items(get_raw_page('customers', (SELECT relpages - 1 FROM pg_class WHERE relname = 'customers')::int))
UNION ALL
SELECT 'order_items', count(*), min(lp_len), max(lp_len)
FROM heap_page_items(get_raw_page('order_items', 0));

-- (2) 実際のページ数と行数
SELECT relname, relpages, reltuples::bigint
FROM pg_class WHERE relname IN ('customers', 'order_items') ORDER BY relname;

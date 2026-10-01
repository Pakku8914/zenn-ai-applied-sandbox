-- 横断復習①: 主キーで 1 行を引くときに読むページ数と、B+木の高さ（S03・S04）。
-- 前提: tools/reset.sh の直後。1 回目はキャッシュの状態で hit と read の内訳が変わるので、2 回ずつ実行する
EXPLAIN (ANALYZE, BUFFERS) SELECT * FROM customers WHERE id = 12345;
EXPLAIN (ANALYZE, BUFFERS) SELECT * FROM customers WHERE id = 12345;
EXPLAIN (ANALYZE, BUFFERS) SELECT * FROM orders WHERE id = 123456;
EXPLAIN (ANALYZE, BUFFERS) SELECT * FROM orders WHERE id = 123456;

-- B+木の高さ（level はリーフを 0 として数えたルートページの段数）
SELECT 'customers_pkey' AS index_name, level, (SELECT relpages FROM pg_class WHERE relname = 'customers_pkey') AS pages
FROM bt_metap('customers_pkey')
UNION ALL
SELECT 'orders_pkey', level, (SELECT relpages FROM pg_class WHERE relname = 'orders_pkey')
FROM bt_metap('orders_pkey');

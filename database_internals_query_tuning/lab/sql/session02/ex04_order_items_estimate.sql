-- 演習 S02-ex04: order_items（全列が固定長）のページ数を見積もる
-- bigint 8 + bigint 8 + integer 4 + integer 4 + integer 4 = 28 バイト。ヘッダ 24 を足して 52
SELECT pg_column_size(oi.*) AS row_bytes FROM order_items oi WHERE id = 1;

-- 52 → 8 バイト境界に切り上げて 56 → 行ポインタ込み 60 → 8168 / 60 = 136 行/ページ → 2000000 / 136 = 14705.9 → 14706
SELECT floor(8168 / 60.0) AS rows_per_page, ceil(2000000 / floor(8168 / 60.0)) AS est_pages,
       (SELECT relpages FROM pg_class WHERE relname = 'order_items') AS relpages;

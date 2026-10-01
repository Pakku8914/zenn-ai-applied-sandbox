-- 演習 S02-ex01: products の 0 ページ目の空き領域と行ポインタの数
SELECT lower, upper,
       upper - lower    AS free_bytes,
       (lower - 24) / 4 AS line_pointers
FROM page_header(get_raw_page('products', 0));

SELECT count(*) AS tuples FROM heap_page_items(get_raw_page('products', 0));

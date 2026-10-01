-- セッション2-2: 0 ページ目の行ポインタとタプルを 1 つずつ見る
-- lp     : 行ポインタの番号（1 始まり）
-- lp_off : 行本体がページ先頭から何バイト目にあるか
-- lp_len : 行本体の長さ（タプルヘッダ込み）
-- t_hoff : タプルヘッダの長さ（ここから列の値が始まる）
-- t_ctid : この版の位置（更新されていなければ自分自身）
SELECT lp, lp_off, lp_flags, lp_len, t_hoff, t_ctid
FROM heap_page_items(get_raw_page('orders', 0))
ORDER BY lp
LIMIT 8;

-- 行本体はページの末尾から先頭に向かって詰めて置かれる。
-- 1 つ前の行本体との位置の差が「その行がページ上で占めるバイト数（8 バイト境界への切り上げ込み）」
SELECT lp, lp_off, lp_len,
       coalesce(lag(lp_off) OVER (ORDER BY lp), 8192) - lp_off AS bytes_on_page
FROM heap_page_items(get_raw_page('orders', 0))
ORDER BY lp
LIMIT 8;

-- 0 ページ目のタプル数と、行の長さの分布
SELECT lp_len, count(*) AS tuples
FROM heap_page_items(get_raw_page('orders', 0))
GROUP BY lp_len
ORDER BY lp_len;

-- 長さが違う行（lp=7）は何が違うのか。ctid を指定して取り出す
SELECT ctid, * FROM orders WHERE ctid IN ('(0,6)', '(0,7)', '(0,8)');

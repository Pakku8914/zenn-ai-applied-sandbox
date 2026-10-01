-- セッション2-1: orders の 0 ページ目のヘッダを読む
-- get_raw_page は 8KB のページを 1 枚そのまま取り出す。page_header はその先頭 24 バイト（ページヘッダ）を表にする
SELECT * FROM page_header(get_raw_page('orders', 0));

-- lower = 行ポインタの並びが終わる位置、upper = 行本体が始まる位置。その間が空き領域
-- 行ポインタは 1 個 4 バイトで、24 バイトのページヘッダの直後から並ぶ
SELECT lower,
       upper,
       upper - lower    AS free_bytes,
       (lower - 24) / 4 AS line_pointers
FROM page_header(get_raw_page('orders', 0));

-- ページの大きさ（コンパイル時に決まる。既定 8192 バイト）
SHOW block_size;

-- セッション2-5: 1 行の大きさからページ数を見積もり、実際のページ数と突き合わせる

-- 列ごとの大きさ（バイト）。pg_column_size(o.*) は行全体（タプルヘッダ 24 バイト込み）で、lp_len と一致する
-- status は 'completed'（9 文字）と 'pending'（7 文字）で 2 バイト違う。text は 1 バイトの長さヘッダ＋本体
SELECT id, status,
       pg_column_size(o.id)          AS id_bytes,
       pg_column_size(o.customer_id) AS customer_id_bytes,
       pg_column_size(o.ordered_at)  AS ordered_at_bytes,
       pg_column_size(o.status)      AS status_bytes,
       pg_column_size(o.*)           AS row_bytes
FROM orders o
WHERE id IN (1, 7);

-- 見積もりの手順（1 ページに使えるのは 8192 - ページヘッダ 24 = 8168 バイト）
--   1) 代表的な 1 行の長さ L（最も多い長さ）
--   2) 8 バイト境界に切り上げる       aligned = ceil(L / 8) * 8
--   3) 行ポインタ 4 バイトを足す       per_row = aligned + 4
--   4) 1 ページの行数（切り捨て）      rows_per_page = floor(8168 / per_row)
--   5) ページ数（切り上げ）            est_pages = ceil(行数 / rows_per_page)
WITH typical AS (
    SELECT 'customers' AS relname, mode() WITHIN GROUP (ORDER BY pg_column_size(x.*)) AS row_len FROM customers x
    UNION ALL
    SELECT 'products', mode() WITHIN GROUP (ORDER BY pg_column_size(x.*)) FROM products x
    UNION ALL
    SELECT 'orders', mode() WITHIN GROUP (ORDER BY pg_column_size(x.*)) FROM orders x
    UNION ALL
    SELECT 'order_items', mode() WITHIN GROUP (ORDER BY pg_column_size(x.*)) FROM order_items x
), est AS (
    SELECT t.relname, t.row_len,
           ceil(t.row_len / 8.0) * 8                        AS aligned,
           ceil(t.row_len / 8.0) * 8 + 4                    AS per_row,
           floor(8168 / (ceil(t.row_len / 8.0) * 8 + 4))    AS rows_per_page,
           c.reltuples::bigint                              AS reltuples,
           c.relpages
    FROM typical t
    JOIN pg_class c ON c.relname = t.relname AND c.relnamespace = 'public'::regnamespace
)
SELECT relname, row_len, aligned, per_row, rows_per_page,
       ceil(reltuples / rows_per_page)                                        AS est_pages,
       relpages,
       round(100.0 * (ceil(reltuples / rows_per_page) - relpages) / relpages, 1) AS diff_pct
FROM est
ORDER BY relpages;

-- orders だけ見積もりがずれる理由: 行の長さが 1 種類ではない
SELECT status, pg_column_size(o.*) AS row_len,
       ceil(pg_column_size(o.*) / 8.0) * 8 + 4 AS per_row,
       count(*) AS rows
FROM orders o
GROUP BY 1, 2
ORDER BY 1;

-- 行ごとの per_row の平均で計算し直す
SELECT round(avg(ceil(pg_column_size(o.*) / 8.0) * 8 + 4), 4)            AS avg_per_row,
       floor(8168 / avg(ceil(pg_column_size(o.*) / 8.0) * 8 + 4))          AS rows_per_page,
       ceil(count(*) / floor(8168 / avg(ceil(pg_column_size(o.*) / 8.0) * 8 + 4))) AS est_pages
FROM orders o;

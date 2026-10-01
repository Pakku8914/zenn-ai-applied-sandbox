-- 演習 S02-ex03: customers のページ数を 1 行の大きさから見積もる
-- 代表的な行（id が 5 桁）の列の大きさ
SELECT id,
       pg_column_size(c.id)         AS id_bytes,
       pg_column_size(c.name)       AS name_bytes,
       pg_column_size(c.email)      AS email_bytes,
       pg_column_size(c.region)     AS region_bytes,
       pg_column_size(c.created_at) AS created_at_bytes,
       pg_column_size(c.*)          AS row_bytes
FROM customers c
WHERE id = 12345;

-- 80 バイト → 8 の倍数なのでそのまま 80 → 行ポインタ込み 84 → 8168 / 84 = 97 行/ページ → 50000 / 97 = 515.5 → 516 ページ
SELECT floor(8168 / 84.0) AS rows_per_page, ceil(50000 / floor(8168 / 84.0)) AS est_pages,
       (SELECT relpages FROM pg_class WHERE relname = 'customers') AS relpages;

-- 演習 S02-ex10: customers の 0 ページ目には平均（96.9 行）より多くの行が入っている。なぜか
SELECT count(*) AS tuples FROM heap_page_items(get_raw_page('customers', 0));

SELECT lp_len, count(*) AS tuples, min(t_ctid) AS first_ctid, max(t_ctid) AS last_ctid
FROM heap_page_items(get_raw_page('customers', 0))
GROUP BY lp_len
ORDER BY lp_len;

-- id の桁数が少ない行は name（'顧客' || id）と email（'user' || id || '@example.com'）が短い。
-- ただし region が '名古屋'（3 文字 = 9 バイト）の行は、桁数が少なくても 8 バイト境界を 1 つ越える
SELECT id, name, email, region, pg_column_size(c.*) AS row_bytes
FROM customers c
WHERE id IN (9, 10, 12, 99, 100, 12345)
ORDER BY id;

-- 桁数と地域の組み合わせごとの行の長さ（0 ページ目の lp_len と ctid で突き合わせる）
SELECT c.id, c.region, h.lp_len
FROM heap_page_items(get_raw_page('customers', 0)) AS h
JOIN customers c ON c.ctid = h.t_ctid
WHERE c.id IN (1, 2, 5, 10, 11, 12, 100, 101, 102)
ORDER BY c.id;

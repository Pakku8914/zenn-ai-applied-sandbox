-- セッション2-3: ctid（行の物理位置）を確かめる
-- ctid は（ページ番号, ページ内の行ポインタ番号）
SELECT ctid, * FROM orders WHERE id IN (1, 2, 122, 123, 124) ORDER BY id;

-- ctid を指定して 1 行を直接取り出す。Tid Scan はインデックスもページの走査も使わない
EXPLAIN (ANALYZE, BUFFERS) SELECT * FROM orders WHERE ctid = '(1,1)';

-- ページごとの行数（ctid の前半がページ番号）。先頭 3 ページ
SELECT (ctid::text::point)[0]::bigint AS page, count(*) AS tuples
FROM orders
GROUP BY 1
ORDER BY 1
LIMIT 3;

-- 行が入っているページの数と、1 ページあたりの行数の最小・最大
SELECT count(*) AS pages, min(tuples) AS min_tuples, max(tuples) AS max_tuples
FROM (SELECT (ctid::text::point)[0]::bigint AS page, count(*) AS tuples
      FROM orders GROUP BY 1) AS t;

-- 行数が少ないのはどのページか
SELECT page, tuples
FROM (SELECT (ctid::text::point)[0]::bigint AS page, count(*) AS tuples
      FROM orders GROUP BY 1) AS t
WHERE tuples < 122;

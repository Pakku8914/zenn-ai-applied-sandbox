-- Bitmap Heap Scan がヒープを「ページ単位・物理順」に読み直していることを確かめる。
-- 前提: 01_create_indexes.sql 実行済み

-- (1) 条件に合う行が何ページに散らばっているか（ctid の前半がページ番号）
SELECT '1日' AS 範囲, count(*) AS 行数,
       count(DISTINCT (ctid::text::point)[0]) AS ページ数
FROM orders WHERE ordered_at >= '2025-06-01' AND ordered_at < '2025-06-02'
UNION ALL
SELECT '1週間', count(*), count(DISTINCT (ctid::text::point)[0])
FROM orders WHERE ordered_at >= '2025-06-01' AND ordered_at < '2025-06-08';

-- (2) 1 週間: プランナの選択（Bitmap Heap Scan）
EXPLAIN (ANALYZE, BUFFERS)
SELECT * FROM orders WHERE ordered_at >= '2025-06-01' AND ordered_at < '2025-06-08';

-- (3) 同じクエリを Index Scan に強制する（学習用）。インデックスの順にヒープを 1 行ずつ読む
SET enable_bitmapscan = off;
SET enable_seqscan = off;
EXPLAIN (ANALYZE, BUFFERS)
SELECT * FROM orders WHERE ordered_at >= '2025-06-01' AND ordered_at < '2025-06-08';
RESET enable_bitmapscan;
RESET enable_seqscan;

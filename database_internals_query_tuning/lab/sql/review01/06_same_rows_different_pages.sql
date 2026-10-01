-- 横断復習①: 同じ 2,740 行を返す 2 つのクエリが、読むヒープページ数で 100 倍違う理由（S02・S05）。
CREATE INDEX orders_ordered_at_idx ON orders (ordered_at);

-- (A) 1 日分（日付は物理順と相関しない）
EXPLAIN (ANALYZE, BUFFERS)
SELECT * FROM orders WHERE ordered_at >= '2025-06-01' AND ordered_at < '2025-06-02';

-- (B) id で 2,740 行（id は物理順と完全に相関する）
EXPLAIN (ANALYZE, BUFFERS)
SELECT * FROM orders WHERE id BETWEEN 100001 AND 102740;

-- 行が何ページに散らばっているか
SELECT 'A: 1日分' AS 条件, count(*) AS 行数, count(DISTINCT (ctid::text::point)[0]) AS ページ数
FROM orders WHERE ordered_at >= '2025-06-01' AND ordered_at < '2025-06-02'
UNION ALL
SELECT 'B: id 範囲', count(*), count(DISTINCT (ctid::text::point)[0])
FROM orders WHERE id BETWEEN 100001 AND 102740;

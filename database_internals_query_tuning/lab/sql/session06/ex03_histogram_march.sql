-- 練習（模範解答・応用）: 2025-03-01 以上 2025-03-15 未満の見積もりをヒストグラムから手計算する（03_estimate_histogram.sql の範囲を変えただけ）。
WITH h AS (
  SELECT histogram_bounds::text::timestamptz[] AS b
  FROM pg_stats WHERE tablename = 'orders' AND attname = 'ordered_at'
), pos AS (
  SELECT v.name,
         (SELECT (i - 1 + extract(epoch FROM v.x - h.b[i]) / extract(epoch FROM h.b[i + 1] - h.b[i]))
                 / (array_length(h.b, 1) - 1)
          FROM generate_series(1, array_length(h.b, 1) - 1) AS i
          WHERE h.b[i] <= v.x AND v.x < h.b[i + 1]) AS position
  FROM h, (VALUES ('下端', timestamptz '2025-03-01'), ('上端', timestamptz '2025-03-15')) AS v(name, x)
)
SELECT round((max(position) FILTER (WHERE name = '上端') - max(position) FILTER (WHERE name = '下端'))
             * (SELECT reltuples FROM pg_class WHERE relname = 'orders')) AS 手計算の見積もり
FROM pos;
EXPLAIN SELECT * FROM orders WHERE ordered_at >= '2025-03-01' AND ordered_at < '2025-03-15';
SELECT count(*) AS 実際の行数 FROM orders WHERE ordered_at >= '2025-03-01' AND ordered_at < '2025-03-15';

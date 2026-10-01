-- 範囲条件の見積もりを、ヒストグラムから手計算で再現する。
-- 各区間には同じ数（1%）の行が入っているとみなし、区間の中は値が一様に並んでいると仮定して按分する。
--   位置(x) = (x より小さい完全な区間の数 + x を含む区間の中での割合) / 区間の数
--   選択率  = 位置(上端) − 位置(下端)
WITH h AS (
  SELECT histogram_bounds::text::timestamptz[] AS b
  FROM pg_stats WHERE tablename = 'orders' AND attname = 'ordered_at'
), pos AS (
  SELECT v.name, v.x,
         (SELECT (i - 1 + extract(epoch FROM v.x - h.b[i]) / extract(epoch FROM h.b[i + 1] - h.b[i]))
                 / (array_length(h.b, 1) - 1)
          FROM generate_series(1, array_length(h.b, 1) - 1) AS i
          WHERE h.b[i] <= v.x AND v.x < h.b[i + 1]) AS position
  FROM h, (VALUES ('下端', timestamptz '2025-06-01'), ('上端', timestamptz '2025-06-08')) AS v(name, x)
)
SELECT max(position) FILTER (WHERE name = '上端') - max(position) FILTER (WHERE name = '下端') AS 選択率,
       round((max(position) FILTER (WHERE name = '上端') - max(position) FILTER (WHERE name = '下端'))
             * (SELECT reltuples FROM pg_class WHERE relname = 'orders')) AS 手計算の見積もり
FROM pos;

EXPLAIN SELECT * FROM orders WHERE ordered_at >= '2025-06-01' AND ordered_at < '2025-06-08';

-- 実測と比べる
SELECT count(*) AS 実際の行数 FROM orders WHERE ordered_at >= '2025-06-01' AND ordered_at < '2025-06-08';

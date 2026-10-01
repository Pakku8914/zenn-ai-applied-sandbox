-- セッション4-8: 同じ結果を返す 3 つのクエリの実行計画を比べる
-- 「2025-06-01 に注文した顧客の一覧」

-- (A) IN（サブクエリ）
EXPLAIN (ANALYZE, BUFFERS)
SELECT * FROM customers
WHERE id IN (SELECT customer_id FROM orders
             WHERE ordered_at >= '2025-06-01' AND ordered_at < '2025-06-02');

-- (B) EXISTS
EXPLAIN (ANALYZE, BUFFERS)
SELECT * FROM customers c
WHERE EXISTS (SELECT 1 FROM orders o
              WHERE o.customer_id = c.id
                AND o.ordered_at >= '2025-06-01' AND o.ordered_at < '2025-06-02');

-- (C) JOIN + DISTINCT
EXPLAIN (ANALYZE, BUFFERS)
SELECT DISTINCT c.*
FROM customers c
JOIN orders o ON o.customer_id = c.id
WHERE o.ordered_at >= '2025-06-01' AND o.ordered_at < '2025-06-02';

-- 3 つの結果が同じであることの確認（件数と、差集合が空であること）
SELECT
  (SELECT count(*) FROM customers
   WHERE id IN (SELECT customer_id FROM orders
                WHERE ordered_at >= '2025-06-01' AND ordered_at < '2025-06-02')) AS in_rows,
  (SELECT count(*) FROM customers c
   WHERE EXISTS (SELECT 1 FROM orders o WHERE o.customer_id = c.id
                 AND o.ordered_at >= '2025-06-01' AND o.ordered_at < '2025-06-02')) AS exists_rows,
  (SELECT count(*) FROM (SELECT DISTINCT c.* FROM customers c JOIN orders o ON o.customer_id = c.id
                         WHERE o.ordered_at >= '2025-06-01' AND o.ordered_at < '2025-06-02') t) AS distinct_rows;

SELECT count(*) AS diff_rows FROM (
  (SELECT * FROM customers
   WHERE id IN (SELECT customer_id FROM orders
                WHERE ordered_at >= '2025-06-01' AND ordered_at < '2025-06-02'))
  EXCEPT
  (SELECT DISTINCT c.* FROM customers c JOIN orders o ON o.customer_id = c.id
   WHERE o.ordered_at >= '2025-06-01' AND o.ordered_at < '2025-06-02')
) d;

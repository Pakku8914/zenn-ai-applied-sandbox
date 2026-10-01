-- S08-07 work_mem は「クエリごと」でも「接続ごと」でもなく、ソート・ハッシュの「ノードごと」に使われる
-- 「2025年1〜3月の顧客別売上と、その売上順位（顧客番号順に表示）」
--   Hash（結合）・HashAggregate（顧客別集計）・Sort（順位のため）・Sort（表示順のため）の 4 ノードがそれぞれメモリを使う

-- (1) 並列なし：各ノードの Memory Usage / Memory を足すと work_mem（8MB）を超える
SET max_parallel_workers_per_gather = 0;
EXPLAIN (ANALYZE, BUFFERS)
SELECT o.customer_id,
       count(*) AS lines,
       sum(oi.quantity * oi.unit_price) AS sales,
       rank() OVER (ORDER BY sum(oi.quantity * oi.unit_price) DESC) AS sales_rank
FROM orders o
JOIN order_items oi ON oi.order_id = o.id
WHERE o.ordered_at >= '2025-01-01' AND o.ordered_at < '2025-04-01'
  AND o.status <> 'cancelled'
GROUP BY o.customer_id
ORDER BY o.customer_id;
RESET max_parallel_workers_per_gather;

-- (2) 並列あり：ワーカーもそれぞれ自分の分のメモリを使う（Worker 0 / Worker 1 の行）
EXPLAIN (ANALYZE, BUFFERS)
SELECT o.customer_id,
       count(*) AS lines,
       sum(oi.quantity * oi.unit_price) AS sales,
       rank() OVER (ORDER BY sum(oi.quantity * oi.unit_price) DESC) AS sales_rank
FROM orders o
JOIN order_items oi ON oi.order_id = o.id
WHERE o.ordered_at >= '2025-01-01' AND o.ordered_at < '2025-04-01'
  AND o.status <> 'cancelled'
GROUP BY o.customer_id
ORDER BY o.customer_id;

-- (3) 上位 3 人
SELECT customer_id, lines, sales, sales_rank
FROM (
  SELECT o.customer_id,
         count(*) AS lines,
         sum(oi.quantity * oi.unit_price) AS sales,
         rank() OVER (ORDER BY sum(oi.quantity * oi.unit_price) DESC) AS sales_rank
  FROM orders o
  JOIN order_items oi ON oi.order_id = o.id
  WHERE o.ordered_at >= '2025-01-01' AND o.ordered_at < '2025-04-01'
    AND o.status <> 'cancelled'
  GROUP BY o.customer_id
) AS s
ORDER BY sales_rank, customer_id
LIMIT 3;

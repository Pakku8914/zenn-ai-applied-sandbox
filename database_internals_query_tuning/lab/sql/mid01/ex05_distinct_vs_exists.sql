-- Mid01-ex05 「DISTINCT をやめて EXISTS にすれば速い」は本当か
-- 題材：2025 年 6 月に「書籍」カテゴリの商品を含む注文の一覧。01 を実行した後の状態で実行する

-- (1) 結合してから DISTINCT で重複を消す書き方
EXPLAIN (ANALYZE, BUFFERS)
SELECT DISTINCT o.id, o.ordered_at
FROM orders o
JOIN order_items oi ON oi.order_id = o.id
JOIN products p ON p.id = oi.product_id
WHERE p.category = '書籍'
  AND o.ordered_at >= '2025-06-01' AND o.ordered_at < '2025-07-01';

-- (2) EXISTS（準結合）で書く書き方
EXPLAIN (ANALYZE, BUFFERS)
SELECT o.id, o.ordered_at
FROM orders o
WHERE o.ordered_at >= '2025-06-01' AND o.ordered_at < '2025-07-01'
  AND EXISTS (SELECT 1 FROM order_items oi JOIN products p ON p.id = oi.product_id
              WHERE oi.order_id = o.id AND p.category = '書籍');

-- (3) 件数は同じ
SELECT
  (SELECT count(*) FROM (SELECT DISTINCT o.id FROM orders o
     JOIN order_items oi ON oi.order_id = o.id JOIN products p ON p.id = oi.product_id
     WHERE p.category = '書籍' AND o.ordered_at >= '2025-06-01' AND o.ordered_at < '2025-07-01') d) AS by_distinct,
  (SELECT count(*) FROM orders o
     WHERE o.ordered_at >= '2025-06-01' AND o.ordered_at < '2025-07-01'
       AND EXISTS (SELECT 1 FROM order_items oi JOIN products p ON p.id = oi.product_id
                   WHERE oi.order_id = o.id AND p.category = '書籍')) AS by_exists;

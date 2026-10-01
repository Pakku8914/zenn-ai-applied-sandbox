-- Mid01-08 遅いクエリ C（改善前）：管理画面の「未処理（pending）の注文」一覧。新しい順に 20 件
-- 番号を振って 20 番までを取る書き方（row_number）で、上位 20 件を求めている
EXPLAIN (ANALYZE, BUFFERS)
SELECT id, customer_id, ordered_at
FROM (
  SELECT id, customer_id, ordered_at,
         row_number() OVER (ORDER BY ordered_at DESC) AS rn
  FROM orders
  WHERE status = 'pending'
) t
WHERE rn <= 20
ORDER BY rn;

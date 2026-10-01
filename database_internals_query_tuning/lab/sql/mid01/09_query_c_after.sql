-- Mid01-09 遅いクエリ C（改善後）：上位 N 件は ORDER BY ... LIMIT で書く
-- 「20 件で止めてよい」ことがプランナに伝わり、orders_ordered_at_idx を新しい側から読んで 20 件で止まる
EXPLAIN (ANALYZE, BUFFERS)
SELECT id, customer_id, ordered_at
FROM orders
WHERE status = 'pending'
ORDER BY ordered_at DESC
LIMIT 20;

-- 改善前と結果が同じか（並びも含めて比べる。ordered_at はこのデータでは重複しない）
SELECT count(*) AS same_rows
FROM (
  SELECT id, row_number() OVER (ORDER BY ordered_at DESC) AS pos
  FROM (SELECT id, ordered_at FROM orders WHERE status = 'pending' ORDER BY ordered_at DESC LIMIT 20) x
) after_q
JOIN (
  SELECT id, rn AS pos
  FROM (SELECT id, row_number() OVER (ORDER BY ordered_at DESC) AS rn FROM orders WHERE status = 'pending') t
  WHERE rn <= 20
) before_q USING (id, pos);

-- 結果の先頭 5 行
SELECT id, customer_id, ordered_at
FROM orders
WHERE status = 'pending'
ORDER BY ordered_at DESC
LIMIT 5;

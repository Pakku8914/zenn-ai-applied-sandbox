-- Mid01-04 遅いクエリ A（改善後）：列には関数を掛けず、入力の側だけを小文字にする
-- 前提：保存時にメールアドレスを小文字へそろえている（03 の (3) で 0 件を確認した）
EXPLAIN (ANALYZE, BUFFERS)
SELECT o.id, o.ordered_at, o.status
FROM customers c
JOIN orders o ON o.customer_id = c.id
WHERE c.email = lower('User12345@Example.com')
ORDER BY o.ordered_at DESC;

-- 改善前と結果が同じか（差集合が両方向とも 0 行なら同じ）
SELECT count(*) AS only_before FROM (
  SELECT o.id FROM customers c JOIN orders o ON o.customer_id = c.id
  WHERE lower(c.email) = lower('User12345@Example.com')
  EXCEPT
  SELECT o.id FROM customers c JOIN orders o ON o.customer_id = c.id
  WHERE c.email = lower('User12345@Example.com')
) d;
SELECT count(*) AS only_after FROM (
  SELECT o.id FROM customers c JOIN orders o ON o.customer_id = c.id
  WHERE c.email = lower('User12345@Example.com')
  EXCEPT
  SELECT o.id FROM customers c JOIN orders o ON o.customer_id = c.id
  WHERE lower(c.email) = lower('User12345@Example.com')
) d;

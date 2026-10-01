-- Mid01-02 遅いクエリ A（改善前）：サポート画面。入力されたメールアドレスで顧客を探し、注文履歴を新しい順に出す
-- 大文字・小文字の違いを無視したいので、列と入力の両方に lower() を掛けている
EXPLAIN (ANALYZE, BUFFERS)
SELECT o.id, o.ordered_at, o.status
FROM customers c
JOIN orders o ON o.customer_id = c.id
WHERE lower(c.email) = lower('User12345@Example.com')
ORDER BY o.ordered_at DESC;

-- 結果（先頭 5 行と件数）
SELECT o.id, o.ordered_at, o.status
FROM customers c
JOIN orders o ON o.customer_id = c.id
WHERE lower(c.email) = lower('User12345@Example.com')
ORDER BY o.ordered_at DESC
LIMIT 5;

SELECT count(*) AS orders
FROM customers c
JOIN orders o ON o.customer_id = c.id
WHERE lower(c.email) = lower('User12345@Example.com');

-- Mid01-ex01 クエリ A の「効かない改善案」と「結果が変わる書き換え」を確かめる
-- 01 を実行した後の状態（インデックス 3 本がある）で実行する

-- (1) 「統計が古いのでは」と ANALYZE しても、lower(email) の統計は作られないので見積もりも計画も変わらない
ANALYZE customers;
EXPLAIN
SELECT o.id, o.ordered_at, o.status
FROM customers c JOIN orders o ON o.customer_id = c.id
WHERE lower(c.email) = lower('User12345@Example.com')
ORDER BY o.ordered_at DESC;

-- (2) lower() を丸ごと外すと速いが、大文字を含む入力では 1 件も一致しない（結果が変わる）
SELECT count(*) AS orders
FROM customers c JOIN orders o ON o.customer_id = c.id
WHERE c.email = 'User12345@Example.com';

-- (3) ILIKE（大文字・小文字を区別しない LIKE）に書き換えても、B-tree インデックスは使えない
EXPLAIN
SELECT id FROM customers WHERE email ILIKE 'User12345@Example.com';

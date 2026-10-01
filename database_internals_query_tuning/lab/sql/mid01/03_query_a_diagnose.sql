-- Mid01-03 遅いクエリ A の診断：インデックスはあるのに、なぜ 2 本とも使われないのか

-- (1) customers だけを取り出して見積もりを見る：rows=250 は 50,000 行 × 0.5%（関数を掛けた列の「既定の選択率」）
EXPLAIN
SELECT id FROM customers WHERE lower(email) = lower('User12345@Example.com');

-- (2) 統計は email 列にはあるが、lower(email) という「式」には無い（ANALYZE しても作られない）
SELECT attname, n_distinct, null_frac
FROM pg_stats
WHERE tablename = 'customers' AND attname = 'email';

-- (3) 保存されているメールアドレスに大文字が含まれるか：0 件なら「入力側だけ小文字にする」書き換えが安全
SELECT count(*) AS not_lowercase
FROM customers
WHERE email <> lower(email);

-- (4) 見積もりを 1 行にしたら orders の側がどう変わるか：関数を外した形（入力だけ lower）を EXPLAIN する
EXPLAIN
SELECT o.id, o.ordered_at, o.status
FROM customers c
JOIN orders o ON o.customer_id = c.id
WHERE c.email = lower('User12345@Example.com')
ORDER BY o.ordered_at DESC;

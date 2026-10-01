-- 演習 S03-ex10: 前方一致の LIKE が、どんな範囲条件に書き換えられるか（08_like_patterns.sql の後に実行）
EXPLAIN SELECT * FROM customers WHERE email LIKE 'user99%';

-- 実際に何件当たるか（user99, user990〜user999, user9900〜user9999 の 111 件）
SELECT count(*) FROM customers WHERE email LIKE 'user99%';
SELECT count(*) FROM customers WHERE email >= 'user99' AND email < 'user9:';

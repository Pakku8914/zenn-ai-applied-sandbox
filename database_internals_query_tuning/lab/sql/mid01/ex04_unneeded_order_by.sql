-- Mid01-ex04 別の「ソートの無駄」：集計の前の不要な ORDER BY
-- 01 を実行した後の状態で実行する

-- (1) サブクエリの中に ORDER BY がある。集計結果の並びには関係しないが、PostgreSQL は取り除かない
EXPLAIN (ANALYZE, BUFFERS)
SELECT status, count(*) AS orders
FROM (SELECT * FROM orders ORDER BY ordered_at) t
GROUP BY status;

-- (2) ORDER BY を消す
EXPLAIN (ANALYZE, BUFFERS)
SELECT status, count(*) AS orders
FROM (SELECT * FROM orders) t
GROUP BY status;

-- (3) 結果は同じ
SELECT status, count(*) AS orders
FROM (SELECT * FROM orders ORDER BY ordered_at) t
GROUP BY status
ORDER BY status;

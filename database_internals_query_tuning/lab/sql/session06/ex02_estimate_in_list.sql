-- 練習（模範解答・基礎）: customer_id IN (1, 2, 3) の見積もり行数を n_distinct から手計算する。
SELECT n_distinct FROM pg_stats WHERE tablename = 'orders' AND attname = 'customer_id';
EXPLAIN SELECT * FROM orders WHERE customer_id IN (1, 2, 3);
SELECT count(*) AS 実際の行数 FROM orders WHERE customer_id IN (1, 2, 3);

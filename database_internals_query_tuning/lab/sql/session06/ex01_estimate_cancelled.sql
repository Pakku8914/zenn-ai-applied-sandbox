-- 練習（模範解答・基礎）: status = 'cancelled' の見積もり行数を pg_stats から手計算し、EXPLAIN と実際の行数と比べる。
SELECT most_common_vals, most_common_freqs FROM pg_stats
WHERE tablename = 'orders' AND attname = 'status';
SELECT reltuples FROM pg_class WHERE relname = 'orders';
EXPLAIN SELECT * FROM orders WHERE status = 'cancelled';
SELECT count(*) AS 実際の行数 FROM orders WHERE status = 'cancelled';

-- 練習（模範解答）: インデックスが使われないクエリを、同じ結果のまま使われる形に書き換える。
-- 前提: 01_create_indexes.sql 実行済み（status のインデックスは 09_index_not_used.sql と同じものをここでも作る）
CREATE INDEX IF NOT EXISTS orders_status_idx ON orders (status);
-- (1) 月の絞り込み
EXPLAIN SELECT count(*) FROM orders WHERE date_trunc('month', ordered_at) = '2025-06-01';
EXPLAIN SELECT count(*) FROM orders WHERE ordered_at >= '2025-06-01' AND ordered_at < '2025-07-01';
-- (2) 日付の範囲（キャストしてから BETWEEN）
EXPLAIN SELECT * FROM orders WHERE ordered_at::date BETWEEN '2025-06-01' AND '2025-06-03';
EXPLAIN SELECT * FROM orders WHERE ordered_at >= '2025-06-01' AND ordered_at < '2025-06-04';
-- (3) 小数で渡された主キー
EXPLAIN SELECT * FROM customers WHERE id = 777.0;
EXPLAIN SELECT * FROM customers WHERE id = 777;
-- (4) 否定条件
EXPLAIN SELECT count(*) FROM orders WHERE status <> 'completed' AND status <> 'pending';
EXPLAIN SELECT count(*) FROM orders WHERE status = 'cancelled';
-- 結果が同じであることの確認
SELECT (SELECT count(*) FROM orders WHERE date_trunc('month', ordered_at) = '2025-06-01') AS a1,
       (SELECT count(*) FROM orders WHERE ordered_at >= '2025-06-01' AND ordered_at < '2025-07-01') AS b1,
       (SELECT count(*) FROM orders WHERE ordered_at::date BETWEEN '2025-06-01' AND '2025-06-03') AS a2,
       (SELECT count(*) FROM orders WHERE ordered_at >= '2025-06-01' AND ordered_at < '2025-06-04') AS b2,
       (SELECT count(*) FROM orders WHERE status <> 'completed' AND status <> 'pending') AS a4,
       (SELECT count(*) FROM orders WHERE status = 'cancelled') AS b4;

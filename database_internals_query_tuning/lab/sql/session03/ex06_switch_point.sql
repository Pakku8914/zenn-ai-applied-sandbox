-- 演習 S03-ex06: 範囲の幅を変えると、どこで計画が切り替わるか（02_create_index.sql の後に実行）
EXPLAIN SELECT * FROM orders WHERE ordered_at >= '2025-06-01 10:00' AND ordered_at < '2025-06-01 10:01';
EXPLAIN SELECT * FROM orders WHERE ordered_at >= '2025-06-01 10:00' AND ordered_at < '2025-06-01 10:02';
EXPLAIN SELECT * FROM orders WHERE ordered_at >= '2025-06-01' AND ordered_at < '2025-09-01';
EXPLAIN SELECT * FROM orders WHERE ordered_at >= '2025-06-01' AND ordered_at < '2025-12-01';

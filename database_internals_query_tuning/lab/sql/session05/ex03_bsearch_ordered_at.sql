-- 練習（模範解答）: ordered_at の範囲で (a) Index Scan → Bitmap、(b) Bitmap → Seq Scan の境界を探す。
-- 前提: 01_create_indexes.sql 実行済み
-- (a) 秒単位。60 秒（Index Scan）と 300 秒（Bitmap）から始める
EXPLAIN SELECT * FROM orders WHERE ordered_at >= '2025-06-01 00:00:00' AND ordered_at < '2025-06-01 00:01:00';
EXPLAIN SELECT * FROM orders WHERE ordered_at >= '2025-06-01 00:00:00' AND ordered_at < '2025-06-01 00:05:00';
EXPLAIN SELECT * FROM orders WHERE ordered_at >= '2025-06-01 00:00:00' AND ordered_at < '2025-06-01 00:03:00';
EXPLAIN SELECT * FROM orders WHERE ordered_at >= '2025-06-01 00:00:00' AND ordered_at < '2025-06-01 00:02:00';
-- (b) 日単位。30 日（Bitmap）と 180 日（Seq Scan）から始める
EXPLAIN SELECT * FROM orders WHERE ordered_at >= '2025-01-01' AND ordered_at < '2025-01-31';
EXPLAIN SELECT * FROM orders WHERE ordered_at >= '2025-01-01' AND ordered_at < '2025-06-30';
EXPLAIN SELECT * FROM orders WHERE ordered_at >= '2025-01-01' AND ordered_at < '2025-04-16';   -- 105 日
EXPLAIN SELECT * FROM orders WHERE ordered_at >= '2025-01-01' AND ordered_at < '2025-05-23';   -- 142 日
EXPLAIN SELECT * FROM orders WHERE ordered_at >= '2025-01-01' AND ordered_at < '2025-06-11';   -- 161 日
-- …以下、差が 1 日になるまで続ける

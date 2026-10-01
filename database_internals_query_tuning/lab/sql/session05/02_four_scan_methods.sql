-- 4 つのスキャン方式が、それぞれ選ばれる代表的なクエリ。
-- 前提: 01_create_indexes.sql 実行済み

-- (1) Seq Scan: インデックスのない列（products.category）で絞る
EXPLAIN (ANALYZE, BUFFERS)
SELECT * FROM products WHERE category = '文具';

-- (2) Index Scan: 主キーで 1 行だけ取る
EXPLAIN (ANALYZE, BUFFERS)
SELECT * FROM customers WHERE id = 12345;

-- (3) Index Only Scan: インデックスの列（ordered_at）だけで答えが出る
EXPLAIN (ANALYZE, BUFFERS)
SELECT count(*) FROM orders
WHERE ordered_at >= '2025-06-01' AND ordered_at < '2025-06-02';

-- (4) Bitmap Heap Scan + Bitmap Index Scan: 同じ範囲で全列を取る
EXPLAIN (ANALYZE, BUFFERS)
SELECT * FROM orders
WHERE ordered_at >= '2025-06-01' AND ordered_at < '2025-06-02';

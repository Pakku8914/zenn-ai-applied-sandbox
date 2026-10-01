-- 練習: 4 つのクエリのスキャン方式を予想してから実行する。
-- 前提: 01_create_indexes.sql 実行済み
EXPLAIN (ANALYZE, BUFFERS) SELECT * FROM products WHERE id = 100;
EXPLAIN (ANALYZE, BUFFERS) SELECT id FROM products WHERE id < 100;
EXPLAIN (ANALYZE, BUFFERS) SELECT * FROM customers WHERE region = '福岡';
EXPLAIN (ANALYZE, BUFFERS) SELECT * FROM products WHERE price < 200;

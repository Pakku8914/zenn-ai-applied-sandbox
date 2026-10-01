-- 横断復習①: Seq Scan のコストをページ数と行数から分解する（S02・S04）。
-- Seq Scan のコスト = ページ数 × seq_page_cost + 行数 × cpu_tuple_cost + 行数 × 条件の演算子数 × cpu_operator_cost
SHOW seq_page_cost;
SHOW cpu_tuple_cost;
SHOW cpu_operator_cost;
SELECT relname, relpages, reltuples FROM pg_class WHERE relname IN ('products', 'customers', 'orders') ORDER BY relpages;

EXPLAIN SELECT * FROM products WHERE category = '文具';                 -- 演算子 1 つ
EXPLAIN SELECT * FROM customers WHERE region = '東京' OR region = '大阪'; -- 演算子 2 つ（インデックスがないので Seq Scan）
SET max_parallel_workers_per_gather = 0;
EXPLAIN SELECT * FROM orders WHERE customer_id = 777;                   -- 演算子 1 つ
RESET max_parallel_workers_per_gather;

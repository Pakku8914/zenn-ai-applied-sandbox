-- 演習 S04-ex08: products と customers の Seq Scan のコストを手で計算し、EXPLAIN と突き合わせる
SELECT relname, relpages, reltuples FROM pg_class WHERE relname IN ('products', 'customers') ORDER BY relname;

SET max_parallel_workers_per_gather = 0;
EXPLAIN SELECT * FROM products;
EXPLAIN SELECT * FROM customers;
EXPLAIN SELECT * FROM customers WHERE region = '東京';
RESET max_parallel_workers_per_gather;

-- products: 37 × 1.0 + 5000 × 0.01 = 87 / customers: 516 + 50000 × 0.01 = 1016 / 条件 1 つで + 50000 × 0.0025 = 1141
SELECT 37 * 1.0 + 5000 * 0.01 AS products_cost,
       516 * 1.0 + 50000 * 0.01 AS customers_cost,
       516 * 1.0 + 50000 * 0.01 + 50000 * 0.0025 AS customers_where_cost;

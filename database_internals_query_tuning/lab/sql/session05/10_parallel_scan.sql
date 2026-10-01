-- 並列スキャンが選ばれる条件を確かめる。
-- 前提: 01_create_indexes.sql 実行済み（このファイルはインデックスを使わないクエリだけを扱う）

-- (1) 大きいテーブル（orders 64MB）: Parallel Seq Scan
EXPLAIN (ANALYZE, BUFFERS)
SELECT count(*) FROM orders WHERE customer_id = 777;

-- (2) 小さいテーブル（products 296kB）: 並列にならない
EXPLAIN (ANALYZE, BUFFERS)
SELECT count(*) FROM products WHERE price > 5000;

-- 並列を検討する下限の大きさ（既定 8MB）
SHOW min_parallel_table_scan_size;
SHOW max_parallel_workers_per_gather;

-- (3) 下限を 0 にしても、並列の起動コスト（parallel_setup_cost）に見合わないので並列にならない
SET min_parallel_table_scan_size = 0;
EXPLAIN SELECT count(*) FROM products WHERE price > 5000;

-- (4) 起動コストと行の受け渡しコストも 0 にすると、ようやく並列になる（学習用。実務で真似しない）
SET parallel_setup_cost = 0;
SET parallel_tuple_cost = 0;
EXPLAIN SELECT count(*) FROM products WHERE price > 5000;
RESET min_parallel_table_scan_size;
RESET parallel_setup_cost;
RESET parallel_tuple_cost;

-- (5) max_parallel_workers_per_gather = 0 で並列を禁止する
SET max_parallel_workers_per_gather = 0;
EXPLAIN (ANALYZE, BUFFERS)
SELECT count(*) FROM orders WHERE customer_id = 777;

-- (6) 上限を 4 に上げても、ワーカー数はテーブルの大きさで決まる（orders 64MB → 2、order_items 115MB → 3）
SET max_parallel_workers_per_gather = 4;
EXPLAIN SELECT count(*) FROM orders WHERE customer_id = 777;
EXPLAIN SELECT count(*) FROM order_items WHERE product_id = 777;
RESET max_parallel_workers_per_gather;

-- 練習（模範解答・応用）: ワーカー数の上限を 4 に上げたとき、Workers Planned は何になるか。
-- 並列ワーカー数はテーブルの大きさで決まる（min_parallel_table_scan_size の 3 倍ごとに 1 人増える）
SELECT relname, pg_size_pretty(pg_relation_size(oid)) AS size
FROM pg_class WHERE relname IN ('customers', 'orders', 'order_items') ORDER BY pg_relation_size(oid);
SET max_parallel_workers_per_gather = 4;
EXPLAIN SELECT count(*) FROM customers WHERE name LIKE '%7%';
EXPLAIN SELECT count(*) FROM orders WHERE customer_id = 777;
EXPLAIN SELECT count(*) FROM order_items WHERE product_id = 777;
RESET max_parallel_workers_per_gather;

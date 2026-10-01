-- S08 練習問題の模範解答：グループの数で HashAggregate のメモリが決まる（入力の行数ではない）
-- どれも work_mem = 8MB（既定）。並列を切って 1 つのハッシュ表の大きさを比べる
-- 03・05・06 で作ったインデックスがあると「並んだ入力」を使う GroupAggregate が選ばれることがあるので、
-- この問題ではインデックスを使うスキャンを禁止して、HashAggregate どうしで比べる
SET max_parallel_workers_per_gather = 0;
SET enable_indexscan = off;
SET enable_indexonlyscan = off;
SET enable_bitmapscan = off;

-- (1) 地域別（5 グループ）：入力は 100万行でもハッシュ表は小さい
EXPLAIN (ANALYZE, TIMING OFF)
SELECT c.region, count(*) FROM orders o JOIN customers c ON c.id = o.customer_id GROUP BY c.region;

-- (2) 顧客別（5万グループ）
EXPLAIN (ANALYZE, TIMING OFF)
SELECT customer_id, count(*) FROM orders GROUP BY customer_id;

-- (3) 注文別（100万グループ）：work_mem × hash_mem_multiplier = 16MB を超えてディスクに退避する
EXPLAIN (ANALYZE, TIMING OFF)
SELECT order_id, count(*) FROM order_items GROUP BY order_id;

RESET max_parallel_workers_per_gather;
RESET enable_indexscan;
RESET enable_indexonlyscan;
RESET enable_bitmapscan;

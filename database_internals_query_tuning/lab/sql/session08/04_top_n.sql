-- S08-04 LIMIT があるときの Top-N ソート：上位 N 件だけを小さなヒープで持ちながら 1 回読む

-- (1) 既定：並列の各ワーカーがそれぞれ上位 10 件を作り、Gather Merge で合流させる
EXPLAIN (ANALYZE, BUFFERS)
SELECT id, order_id, quantity * unit_price AS amount
FROM order_items
ORDER BY amount DESC, id
LIMIT 10;

-- (2) 並列なしで：Sort Method が top-N heapsort になり、使うメモリは数十 kB
SET max_parallel_workers_per_gather = 0;
EXPLAIN (ANALYZE, BUFFERS)
SELECT id, order_id, quantity * unit_price AS amount
FROM order_items
ORDER BY amount DESC, id
LIMIT 10;
RESET max_parallel_workers_per_gather;

-- (3) LIMIT を 10万件にすると、各ワーカーのソートが work_mem を超えて外部ソートになる（ワーカーごとに Disk が出る）
EXPLAIN (ANALYZE, BUFFERS)
SELECT id, order_id, quantity * unit_price AS amount
FROM order_items
ORDER BY amount DESC, id
LIMIT 100000;

-- (4) 上位 10 件
SELECT id, order_id, quantity * unit_price AS amount
FROM order_items
ORDER BY amount DESC, id
LIMIT 10;

-- Mid01-ex03 クエリ C の改善案を比べる：work_mem を上げる / status にインデックス / インデックスなしで LIMIT
-- 01 を実行した後の状態で実行する

-- 案 1：work_mem を上げる。外部ソートは quicksort に変わるが、13 万行を並べることは変わらない
SET work_mem = '64MB';
EXPLAIN (ANALYZE, BUFFERS)
SELECT id, customer_id, ordered_at
FROM (SELECT id, customer_id, ordered_at, row_number() OVER (ORDER BY ordered_at DESC) AS rn
      FROM orders WHERE status = 'pending') t
WHERE rn <= 20
ORDER BY rn;
RESET work_mem;

-- 案 2：絞り込みの列（status）にインデックスを作る。読み方は変わるが、ソートは残る
CREATE INDEX orders_status_idx ON orders (status);
EXPLAIN (ANALYZE, BUFFERS)
SELECT id, customer_id, ordered_at
FROM (SELECT id, customer_id, ordered_at, row_number() OVER (ORDER BY ordered_at DESC) AS rn
      FROM orders WHERE status = 'pending') t
WHERE rn <= 20
ORDER BY rn;
DROP INDEX orders_status_idx;

-- 案 3：LIMIT に書き換えるが、orders_ordered_at_idx が使えない場合（Index Scan を禁止して再現する）
-- Top-N ソート（top-N heapsort）で全件は並べずに済むが、13 万行を読むことは変わらない
SET enable_indexscan = off;
EXPLAIN (ANALYZE, BUFFERS)
SELECT id, customer_id, ordered_at
FROM orders WHERE status = 'pending'
ORDER BY ordered_at DESC
LIMIT 20;
RESET enable_indexscan;

-- 参考：status の条件が無いと、row_number() の書き方でもインデックスの逆順走査が選ばれる
EXPLAIN (ANALYZE, BUFFERS)
SELECT id, customer_id, ordered_at
FROM (SELECT id, customer_id, ordered_at, row_number() OVER (ORDER BY ordered_at DESC) AS rn
      FROM orders) t
WHERE rn <= 20
ORDER BY rn;

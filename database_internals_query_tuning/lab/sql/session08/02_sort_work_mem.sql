-- S08-02 work_mem を上げていくと、どこで内部ソート（quicksort）に切り替わるか
-- SET はこのセッションの中だけで有効。サーバー全体の設定（postgresql.conf）は変えない
-- 注意：work_mem を大きくすると 1 つのソートがその分のメモリを実際に使う。この環境で試すのは 256MB までにする

-- (1) 64MB：まだ external merge
SET work_mem = '64MB';
EXPLAIN (ANALYZE, BUFFERS)
SELECT id, order_id, quantity * unit_price AS amount
FROM order_items
ORDER BY amount DESC, id;

-- (2) 128MB：quicksort（全件をメモリ上で並べる）に切り替わる
SET work_mem = '128MB';
EXPLAIN (ANALYZE, BUFFERS)
SELECT id, order_id, quantity * unit_price AS amount
FROM order_items
ORDER BY amount DESC, id;

RESET work_mem;

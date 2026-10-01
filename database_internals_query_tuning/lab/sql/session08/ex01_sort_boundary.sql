-- S08 練習問題の模範解答：外部ソートと内部ソートの境界になる work_mem を二分探索で絞り込む
-- 64MB で external merge、128MB で quicksort だった（02 の結果）。その間を調べる
-- 見るのは Sort Method の行だけなので、TIMING OFF で実行する

SET work_mem = '96MB';
EXPLAIN (ANALYZE, TIMING OFF)
SELECT id, order_id, quantity * unit_price AS amount FROM order_items ORDER BY amount DESC, id;

SET work_mem = '112MB';
EXPLAIN (ANALYZE, TIMING OFF)
SELECT id, order_id, quantity * unit_price AS amount FROM order_items ORDER BY amount DESC, id;

SET work_mem = '120MB';
EXPLAIN (ANALYZE, TIMING OFF)
SELECT id, order_id, quantity * unit_price AS amount FROM order_items ORDER BY amount DESC, id;

SET work_mem = '124MB';
EXPLAIN (ANALYZE, TIMING OFF)
SELECT id, order_id, quantity * unit_price AS amount FROM order_items ORDER BY amount DESC, id;

SET work_mem = '125MB';
EXPLAIN (ANALYZE, TIMING OFF)
SELECT id, order_id, quantity * unit_price AS amount FROM order_items ORDER BY amount DESC, id;

RESET work_mem;

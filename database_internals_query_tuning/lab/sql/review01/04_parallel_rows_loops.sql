-- 横断復習①: 並列実行の actual rows と loops から、実際に返した行数と読んだ行数を求める（S04・S05）。
EXPLAIN (ANALYZE, BUFFERS) SELECT * FROM orders WHERE customer_id = 777;

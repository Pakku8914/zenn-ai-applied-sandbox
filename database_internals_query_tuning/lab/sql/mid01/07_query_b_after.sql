-- Mid01-07 遅いクエリ B（改善後）：取り込みの直後に ANALYZE する（バッチの手順に 1 行足す）
ANALYZE mid01_import;

EXPLAIN (ANALYZE, BUFFERS)
SELECT count(*) AS dup_lines
FROM mid01_import a
JOIN mid01_import b
  ON b.order_id = a.order_id
 AND b.product_id = a.product_id
 AND b.line_no > a.line_no
WHERE a.batch_date = DATE '2025-12-31'
  AND b.batch_date = DATE '2025-12-31';

-- 統計が当日の値を知った
SELECT attname, n_distinct, most_common_vals, most_common_freqs
FROM pg_stats
WHERE tablename = 'mid01_import' AND attname = 'batch_date';

-- 見つかった重複（改善前と同じ 3 行）
SELECT a.order_id, a.product_id, a.line_no, b.line_no AS dup_line_no
FROM mid01_import a
JOIN mid01_import b
  ON b.order_id = a.order_id
 AND b.product_id = a.product_id
 AND b.line_no > a.line_no
WHERE a.batch_date = DATE '2025-12-31'
  AND b.batch_date = DATE '2025-12-31'
ORDER BY a.order_id;

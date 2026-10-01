-- Mid01-06 遅いクエリ B（改善前）：当日取り込んだ明細に、同じ注文・同じ商品の行が二重に入っていないかを調べる
-- 05 を実行した直後の状態で実行する
EXPLAIN (ANALYZE, BUFFERS)
SELECT count(*) AS dup_lines
FROM mid01_import a
JOIN mid01_import b
  ON b.order_id = a.order_id
 AND b.product_id = a.product_id
 AND b.line_no > a.line_no
WHERE a.batch_date = DATE '2025-12-31'
  AND b.batch_date = DATE '2025-12-31';

-- 診断 (1)：統計が知っている batch_date の値。TRUNCATE しても統計（pg_stats）は消えない
SELECT attname, n_distinct, most_common_vals, most_common_freqs
FROM pg_stats
WHERE tablename = 'mid01_import' AND attname = 'batch_date';

-- 診断 (2)：最後の ANALYZE の後に何行変わったか（変更行数の集計を先に書き出させてから見る）
SELECT pg_stat_force_next_flush();
SELECT relname, n_mod_since_analyze, last_analyze IS NOT NULL AS analyzed_before
FROM pg_stat_user_tables
WHERE relname = 'mid01_import';

-- 診断 (3)：テーブルの大きさの記録。TRUNCATE で relpages = 0・reltuples = -1（未計測）に戻る
SELECT relname, relpages, reltuples, pg_relation_size('mid01_import') / 8192 AS actual_pages
FROM pg_class
WHERE relname = 'mid01_import';

-- Mid01-ex02 クエリ B の改善案を 3 つ比べる：VACUUM / 結合キーのインデックス / ANALYZE
-- どの案も、05 で「統計が昨夜のまま」の状態を作り直してから試す

-- 案 1：VACUUM だけ（ANALYZE は付けない）
\i sql/mid01/05_query_b_nightly_batch.sql
VACUUM mid01_import;
SELECT relpages, reltuples FROM pg_class WHERE relname = 'mid01_import';
SELECT most_common_vals FROM pg_stats WHERE tablename = 'mid01_import' AND attname = 'batch_date';
EXPLAIN (ANALYZE, BUFFERS)
SELECT count(*) AS dup_lines
FROM mid01_import a
JOIN mid01_import b
  ON b.order_id = a.order_id AND b.product_id = a.product_id AND b.line_no > a.line_no
WHERE a.batch_date = DATE '2025-12-31' AND b.batch_date = DATE '2025-12-31';

-- 案 2：結合キーにインデックスを作る（統計はそのまま）
\i sql/mid01/05_query_b_nightly_batch.sql
CREATE INDEX mid01_import_order_product_idx ON mid01_import (order_id, product_id);
EXPLAIN (ANALYZE, BUFFERS)
SELECT count(*) AS dup_lines
FROM mid01_import a
JOIN mid01_import b
  ON b.order_id = a.order_id AND b.product_id = a.product_id AND b.line_no > a.line_no
WHERE a.batch_date = DATE '2025-12-31' AND b.batch_date = DATE '2025-12-31';

-- 案 3：ANALYZE する（07 と同じ。05 で作り直すとテーブルごと作り直すので、案 2 のインデックスは消えている）
\i sql/mid01/05_query_b_nightly_batch.sql
ANALYZE mid01_import;
EXPLAIN (ANALYZE, BUFFERS)
SELECT count(*) AS dup_lines
FROM mid01_import a
JOIN mid01_import b
  ON b.order_id = a.order_id AND b.product_id = a.product_id AND b.line_no > a.line_no
WHERE a.batch_date = DATE '2025-12-31' AND b.batch_date = DATE '2025-12-31';

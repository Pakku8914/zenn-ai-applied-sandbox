-- 横断復習①: 20% の行しか返さない Bitmap Heap Scan が、なぜテーブルの全ページを読むのか（S02・S05）。
CREATE INDEX customers_region_idx ON customers (region);
EXPLAIN (ANALYZE, BUFFERS) SELECT * FROM customers WHERE region = '札幌';
SELECT relpages FROM pg_class WHERE relname = 'customers';
-- 0 ページ目に札幌の顧客は何人いるか
SELECT count(*) FILTER (WHERE region = '札幌') AS 札幌, count(*) AS 全体
FROM customers WHERE (ctid::text::point)[0] = 0;

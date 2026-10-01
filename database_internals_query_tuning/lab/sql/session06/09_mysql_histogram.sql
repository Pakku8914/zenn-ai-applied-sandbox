-- MySQL（InnoDB）での比較。mysql クライアントで実行する:
--   docker compose exec -T lab mysql --skip-ssl -h mysql -ulab shopdb -t < sql/session06/09_mysql_histogram.sql
-- インデックスのない列の条件は、ヒストグラムがなければ固定の割合（等値なら 10%）で見積もられる

-- (1) ヒストグラムなし: filtered 列に注目
ANALYZE TABLE orders DROP HISTOGRAM ON status;
EXPLAIN FORMAT=TRADITIONAL SELECT * FROM orders WHERE status = 'pending';

-- (2) ヒストグラムを作る（ANALYZE TABLE ... UPDATE HISTOGRAM）。PostgreSQL と違い、明示的に作るまで存在しない
ANALYZE TABLE orders UPDATE HISTOGRAM ON status WITH 8 BUCKETS;
SELECT column_name, histogram->>'$."histogram-type"' AS type,
       histogram->>'$."number-of-buckets-specified"' AS buckets,
       histogram->'$.buckets' AS buckets_json
FROM information_schema.column_statistics
WHERE schema_name = DATABASE() AND table_name = 'orders';
EXPLAIN FORMAT=TRADITIONAL SELECT * FROM orders WHERE status = 'pending';

ANALYZE TABLE orders DROP HISTOGRAM ON status;

-- (3) インデックスのある列: 実行計画を作るたびにインデックスを実際に覗いて件数を見積もる（index dive）
CREATE INDEX customers_region_idx ON customers (region);
EXPLAIN ANALYZE SELECT count(*) FROM customers WHERE region = '東京'\G

-- ANALYZE TABLE が集めるインデックスの統計（Cardinality）は、既定 20 ページの標本から作られる
SELECT @@innodb_stats_persistent_sample_pages;
SHOW INDEX FROM customers WHERE Key_name = 'customers_region_idx';

-- index dive を止めると（eq_range_index_dive_limit = 1）、統計（行数 ÷ Cardinality）で見積もる
EXPLAIN FORMAT=TRADITIONAL SELECT * FROM customers WHERE region = '東京';
SET SESSION eq_range_index_dive_limit = 1;
EXPLAIN FORMAT=TRADITIONAL SELECT * FROM customers WHERE region = '東京';
SET SESSION eq_range_index_dive_limit = DEFAULT;

-- セッション4-5: 見積もり（rows）と実測（actual rows）のズレを見つける
-- 「東京の顧客のうち、2024-03-01 に登録した人」
EXPLAIN ANALYZE
SELECT * FROM customers
WHERE region = '東京' AND created_at = '2024-03-01';

-- 同じ日に登録した「大阪の顧客」
EXPLAIN ANALYZE
SELECT * FROM customers
WHERE region = '大阪' AND created_at = '2024-03-01';

-- 条件を 1 つずつにすると、見積もりはほぼ当たる
EXPLAIN ANALYZE SELECT * FROM customers WHERE region = '東京';
EXPLAIN ANALYZE SELECT * FROM customers WHERE created_at = '2024-03-01';

-- ズレの原因の手がかり: 2024-03-01 に登録した顧客は全員が同じ地域
SELECT region, count(*) FROM customers WHERE created_at = '2024-03-01' GROUP BY region;

-- 演習 S04-ex03: 見積もりと実測が大きくずれるノードを見つけ、何倍ずれているか答える
EXPLAIN ANALYZE
SELECT * FROM customers
WHERE region = '福岡' AND created_at = '2024-01-04';

SELECT region, count(*) FROM customers WHERE created_at = '2024-01-04' GROUP BY region;

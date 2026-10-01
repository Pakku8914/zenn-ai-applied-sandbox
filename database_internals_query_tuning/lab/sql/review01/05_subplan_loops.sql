-- 横断復習①: 相関サブクエリの SubPlan が何回実行されたかを loops から読む（S04・S05）。
-- orders.customer_id にはインデックスがない（外部キー制約はインデックスを作らない）
EXPLAIN (ANALYZE, BUFFERS)
SELECT c.id, c.name,
       (SELECT count(*) FROM orders o WHERE o.customer_id = c.id) AS 注文数
FROM customers c
WHERE c.id <= 5;

-- 改善 (1): 結合と集約に書き換える（orders を 1 回だけ読む）
EXPLAIN (ANALYZE, BUFFERS)
SELECT c.id, c.name, count(o.id) AS 注文数
FROM customers c LEFT JOIN orders o ON o.customer_id = c.id
WHERE c.id <= 5
GROUP BY c.id, c.name
ORDER BY c.id;

-- 改善 (2): サブクエリはそのままで、orders.customer_id にインデックスを作る
CREATE INDEX orders_customer_id_idx ON orders (customer_id);
EXPLAIN (ANALYZE, BUFFERS)
SELECT c.id, c.name,
       (SELECT count(*) FROM orders o WHERE o.customer_id = c.id) AS 注文数
FROM customers c
WHERE c.id <= 5;

-- 3 つの書き方の結果が同じであることの確認
SELECT c.id, (SELECT count(*) FROM orders o WHERE o.customer_id = c.id) AS 注文数
FROM customers c WHERE c.id <= 5 ORDER BY c.id;

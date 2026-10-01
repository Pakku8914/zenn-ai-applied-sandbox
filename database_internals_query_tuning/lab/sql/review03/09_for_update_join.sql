-- R03-09 結合したクエリの FOR UPDATE：どのテーブルの行がロックされるか（S07・S10・S11 の復習）
-- \i sql/review03/09_for_update_join.sql（01 の後。数秒で終わる）
-- 行ロックは xmax にトランザクション番号が入ることで確かめる（S10）
SET client_min_messages = warning;
DROP TABLE IF EXISTS r03_customers;
RESET client_min_messages;
CREATE TABLE r03_customers (LIKE customers);
INSERT INTO r03_customers SELECT * FROM customers ORDER BY id;
ALTER TABLE r03_customers ADD PRIMARY KEY (id);
VACUUM (ANALYZE) r03_customers;

-- (1) FOR UPDATE OF o：注文の行だけをロックする。計画の一番上に LockRows が付く
BEGIN;
EXPLAIN (COSTS OFF)
SELECT o.id, o.status, c.name FROM r03_orders AS o JOIN r03_customers AS c ON c.id = o.customer_id
WHERE o.id = 1 FOR UPDATE OF o;
SELECT o.id, o.status, c.name FROM r03_orders AS o JOIN r03_customers AS c ON c.id = o.customer_id
WHERE o.id = 1 FOR UPDATE OF o;
SELECT pg_current_xact_id();
SELECT 'r03_orders' AS tbl, xmax FROM r03_orders WHERE id = 1
UNION ALL
SELECT 'r03_customers', c.xmax FROM r03_customers AS c JOIN r03_orders AS o ON o.customer_id = c.id WHERE o.id = 1;
ROLLBACK;

-- (2) OF を付けない FOR UPDATE：結合したすべてのテーブルの行（顧客の行も）をロックする
BEGIN;
SELECT o.id, o.status, c.name FROM r03_orders AS o JOIN r03_customers AS c ON c.id = o.customer_id
WHERE o.id = 2 FOR UPDATE;
SELECT pg_current_xact_id();
SELECT 'r03_orders' AS tbl, xmax FROM r03_orders WHERE id = 2
UNION ALL
SELECT 'r03_customers', c.xmax FROM r03_customers AS c JOIN r03_orders AS o ON o.customer_id = c.id WHERE o.id = 2;
ROLLBACK;

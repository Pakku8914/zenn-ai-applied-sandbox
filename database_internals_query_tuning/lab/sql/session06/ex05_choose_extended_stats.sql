-- 練習（模範解答・応用）: 3 つのクエリの見積もりを直すのに、どの種類の拡張統計が要るか。
-- Q1: 等値条件 2 つ / Q2: 等値と範囲 / Q3: 2 列の GROUP BY。種類を 1 つずつ作り、3 つのクエリの rows= を比べる
\set q1 'EXPLAIN SELECT * FROM customers WHERE region = ''福岡'' AND created_at = ''2024-01-04'''
\set q2 'EXPLAIN SELECT * FROM customers WHERE region = ''福岡'' AND created_at >= ''2024-01-04'' AND created_at < ''2024-01-05'''
\set q3 'EXPLAIN SELECT region, created_at, count(*) FROM customers GROUP BY region, created_at'
SELECT count(*) AS q1_q2_の実際の行数 FROM customers WHERE region = '福岡' AND created_at = '2024-01-04';

-- (0) 拡張統計なし
:q1; :q2; :q3;

-- (1) dependencies
CREATE STATISTICS s06_ex_dep (dependencies) ON region, created_at FROM customers;
ANALYZE customers;
:q1; :q2; :q3;
DROP STATISTICS s06_ex_dep;

-- (2) ndistinct
CREATE STATISTICS s06_ex_nd (ndistinct) ON region, created_at FROM customers;
ANALYZE customers;
:q1; :q2; :q3;
DROP STATISTICS s06_ex_nd;

-- (3) mcv（統計目標 1000）
CREATE STATISTICS s06_ex_mcv (mcv) ON region, created_at FROM customers;
ALTER STATISTICS s06_ex_mcv SET STATISTICS 1000;
ANALYZE customers;
:q1; :q2; :q3;
DROP STATISTICS s06_ex_mcv;
ANALYZE customers;

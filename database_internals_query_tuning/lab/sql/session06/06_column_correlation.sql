-- 列間の相関: customers の region は created_at の日付から一意に決まる
-- （region = id % 5、created_at の日 = id % 700。700 は 5 の倍数なので、日が決まれば region も決まる）。
-- プランナは条件どうしを独立とみなして選択率を掛け算するので、見積もりが外れる。

-- (0) 実際の行数: 2024-01-01 生まれの顧客は全員「東京」
SELECT region, count(*) FROM customers
WHERE created_at >= '2024-01-01' AND created_at < '2024-01-02' GROUP BY region;

-- (0b) 逆に、2024-01-01 生まれの「大阪」の顧客は 0 人
EXPLAIN (ANALYZE) SELECT * FROM customers
WHERE region = '大阪' AND created_at >= '2024-01-01' AND created_at < '2024-01-02';

-- (1) 拡張統計なし
EXPLAIN (ANALYZE) SELECT * FROM customers
WHERE region = '東京' AND created_at >= '2024-01-01' AND created_at < '2024-01-02';   -- 範囲条件
EXPLAIN (ANALYZE) SELECT * FROM customers
WHERE region = '東京' AND created_at = '2024-01-01';                                  -- 等値条件
EXPLAIN (ANALYZE) SELECT region, created_at, count(*) FROM customers
GROUP BY region, created_at;                                                          -- グループ数

-- (2) 関数従属（dependencies）: 等値条件にだけ効く
CREATE STATISTICS s06_cust_dep (dependencies) ON region, created_at FROM customers;
ANALYZE customers;
SELECT statistics_name, dependencies FROM pg_stats_ext WHERE statistics_name = 's06_cust_dep';
EXPLAIN SELECT * FROM customers
WHERE region = '東京' AND created_at >= '2024-01-01' AND created_at < '2024-01-02';
EXPLAIN SELECT * FROM customers
WHERE region = '東京' AND created_at = '2024-01-01';
DROP STATISTICS s06_cust_dep;

-- (3) 組み合わせの最頻値（mcv）: 既定の統計目標 100 では 700 通りの組み合わせのうち 100 個しか持てない
CREATE STATISTICS s06_cust_mcv (mcv) ON region, created_at FROM customers;
ANALYZE customers;
SELECT statistics_name, array_length(most_common_vals, 1) AS mcv_の件数
FROM pg_stats_ext WHERE statistics_name = 's06_cust_mcv';
EXPLAIN SELECT * FROM customers
WHERE region = '東京' AND created_at >= '2024-01-01' AND created_at < '2024-01-02';

-- (4) 統計目標を 1000 に上げると 700 通りすべてを持てるようになり、範囲条件にも効く
ALTER STATISTICS s06_cust_mcv SET STATISTICS 1000;
ANALYZE customers;
SELECT statistics_name, array_length(most_common_vals, 1) AS mcv_の件数
FROM pg_stats_ext WHERE statistics_name = 's06_cust_mcv';
EXPLAIN (ANALYZE) SELECT * FROM customers
WHERE region = '東京' AND created_at >= '2024-01-01' AND created_at < '2024-01-02';
EXPLAIN SELECT * FROM customers
WHERE region = '東京' AND created_at = '2024-01-01';
DROP STATISTICS s06_cust_mcv;

-- (5) 組み合わせの異なり数（ndistinct）: GROUP BY のグループ数の見積もりに効く
CREATE STATISTICS s06_cust_nd (ndistinct) ON region, created_at FROM customers;
ANALYZE customers;
EXPLAIN SELECT region, created_at, count(*) FROM customers GROUP BY region, created_at;
DROP STATISTICS s06_cust_nd;
ANALYZE customers;

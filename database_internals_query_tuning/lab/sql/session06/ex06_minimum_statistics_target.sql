-- 練習（模範解答・発展）: 常連客 200 人を全員 MCV に載せるには、統計の目標値がいくつ必要か（07_statistics_target.sql の続き）。
CREATE TABLE s06_hot WITH (autovacuum_enabled = false) AS
SELECT i AS id,
       CASE WHEN i <= 200000 THEN 1 + (i % 200)
            ELSE 1 + ((i::bigint * 7919) % 50000)::int END AS customer_id
FROM generate_series(1, 1000000) AS s(i);

-- 目標値を変えるたびに ANALYZE し、MCV に載った常連客の人数を数える
ALTER TABLE s06_hot ALTER COLUMN customer_id SET STATISTICS 150;
ANALYZE s06_hot;
SELECT 150 AS 目標値, count(*) FILTER (WHERE v <= 200) AS 載った常連客, count(*) AS mcv_の件数
FROM pg_stats, unnest(most_common_vals::text::int[]) AS v WHERE tablename = 's06_hot' AND attname = 'customer_id';

ALTER TABLE s06_hot ALTER COLUMN customer_id SET STATISTICS 200;
ANALYZE s06_hot;
SELECT 200 AS 目標値, count(*) FILTER (WHERE v <= 200) AS 載った常連客, count(*) AS mcv_の件数
FROM pg_stats, unnest(most_common_vals::text::int[]) AS v WHERE tablename = 's06_hot' AND attname = 'customer_id';

ALTER TABLE s06_hot ALTER COLUMN customer_id SET STATISTICS 250;
ANALYZE s06_hot;
SELECT 250 AS 目標値, count(*) FILTER (WHERE v <= 200) AS 載った常連客, count(*) AS mcv_の件数
FROM pg_stats, unnest(most_common_vals::text::int[]) AS v WHERE tablename = 's06_hot' AND attname = 'customer_id';

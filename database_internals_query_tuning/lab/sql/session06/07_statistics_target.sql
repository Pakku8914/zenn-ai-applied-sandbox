-- 統計の目標値（ALTER TABLE ... ALTER COLUMN ... SET STATISTICS）を上げると何が変わるか。
-- 4 テーブルの列に設定すると tools/reset.sh では元に戻らないので、作業用テーブル s06_hot で行う。
-- 200 人の「常連客」がそれぞれ約 1,000 件、残り 80 万件は 5 万人にほぼ均等（1 人約 16 件）という偏った分布を作る。
CREATE TABLE s06_hot WITH (autovacuum_enabled = false) AS
SELECT i AS id,
       CASE WHEN i <= 200000 THEN 1 + (i % 200)
            ELSE 1 + ((i::bigint * 7919) % 50000)::int END AS customer_id
FROM generate_series(1, 1000000) AS s(i);
ANALYZE s06_hot;

-- 常連客（customer_id 1〜200）の実際の件数
SELECT min(n), max(n) FROM (SELECT count(*) AS n FROM s06_hot WHERE customer_id <= 200 GROUP BY customer_id) t;

-- (1) 既定（100）: MCV は 100 個まで。常連客 200 人のうち半分しか載らない
SELECT array_length(most_common_vals, 1) AS mcv_の件数
FROM pg_stats WHERE tablename = 's06_hot' AND attname = 'customer_id';

-- MCV に載らなかった常連客を 1 人選ぶ
SELECT min(v) AS hot_id FROM generate_series(1, 200) AS v
WHERE v NOT IN (SELECT unnest(most_common_vals::text::int[]) FROM pg_stats
                WHERE tablename = 's06_hot' AND attname = 'customer_id') \gset
SELECT :hot_id AS mcv_に載らなかった常連客;

EXPLAIN (ANALYZE) SELECT * FROM s06_hot WHERE customer_id = :hot_id;

-- (2) 目標値を 1000 に上げて取り直す（標本は 300 × 1000 = 30 万行に増える）
ALTER TABLE s06_hot ALTER COLUMN customer_id SET STATISTICS 1000;
ANALYZE s06_hot;
SELECT array_length(most_common_vals, 1) AS mcv_の件数
FROM pg_stats WHERE tablename = 's06_hot' AND attname = 'customer_id';

EXPLAIN (ANALYZE) SELECT * FROM s06_hot WHERE customer_id = :hot_id;

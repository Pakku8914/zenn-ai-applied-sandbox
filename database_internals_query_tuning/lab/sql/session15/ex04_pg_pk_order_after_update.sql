-- S15 演習：PostgreSQL のヒープが「主キー順に並んでいる」のは入れた順のおかげ。更新するとどうなるか
-- 作業用コピーで行う（4テーブルは変えない）
DROP TABLE IF EXISTS s15_orders_copy;
CREATE TABLE s15_orders_copy AS SELECT * FROM orders ORDER BY id;
ALTER TABLE s15_orders_copy ADD PRIMARY KEY (id);
VACUUM ANALYZE s15_orders_copy;

-- (1) 更新前：10万行の主キー範囲は約 1,100 ページに収まる
EXPLAIN (ANALYZE, BUFFERS, COSTS OFF)
SELECT * FROM s15_orders_copy WHERE id BETWEEN 200001 AND 300000;

-- (2) 1割の行を更新する。新しい版はページの空きではなく、テーブルの末尾に積まれる
UPDATE s15_orders_copy SET status = status WHERE id % 10 = 0;
VACUUM ANALYZE s15_orders_copy;
SELECT attname, correlation FROM pg_stats WHERE tablename = 's15_orders_copy' AND attname = 'id';

-- (3) 更新後：同じ範囲を読むのに必要なページが増える
EXPLAIN (ANALYZE, BUFFERS, COSTS OFF)
SELECT * FROM s15_orders_copy WHERE id BETWEEN 200001 AND 300000;

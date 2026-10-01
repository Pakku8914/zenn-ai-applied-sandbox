-- S09-06 インデックスを増やすコスト：書き込み・容量・HOT 更新
-- 作業用テーブル s09_w0 / s09_w2 / s09_w5 に、それぞれ 0 本・2 本・5 本のインデックスを貼って比べる
-- fillfactor = 90 は、ページに 1 割の空きを残して HOT 更新の余地を作る設定。autovacuum は比較のため止める

DROP TABLE IF EXISTS s09_w0, s09_w2, s09_w5;
CREATE TABLE s09_w0 (LIKE orders) WITH (fillfactor = 90, autovacuum_enabled = false);
CREATE TABLE s09_w2 (LIKE orders) WITH (fillfactor = 90, autovacuum_enabled = false);
CREATE TABLE s09_w5 (LIKE orders) WITH (fillfactor = 90, autovacuum_enabled = false);
-- 2 本：主キー相当と customer_id
CREATE UNIQUE INDEX s09_w2_id_idx ON s09_w2 (id);
CREATE INDEX s09_w2_customer_id_idx ON s09_w2 (customer_id);
-- 5 本：上の 2 本に ordered_at・status・(customer_id, ordered_at) を足す
CREATE UNIQUE INDEX s09_w5_id_idx ON s09_w5 (id);
CREATE INDEX s09_w5_customer_id_idx ON s09_w5 (customer_id);
CREATE INDEX s09_w5_ordered_at_idx ON s09_w5 (ordered_at);
CREATE INDEX s09_w5_status_idx ON s09_w5 (status);
CREATE INDEX s09_w5_customer_id_ordered_at_idx ON s09_w5 (customer_id, ordered_at);

-- (1) 同じ 10 万行を INSERT する（Execution Time を比べる。インデックスへの書き込みもここに含まれる）
EXPLAIN (ANALYZE, TIMING OFF) INSERT INTO s09_w0 SELECT * FROM orders WHERE id <= 100000;
EXPLAIN (ANALYZE, TIMING OFF) INSERT INTO s09_w2 SELECT * FROM orders WHERE id <= 100000;
EXPLAIN (ANALYZE, TIMING OFF) INSERT INTO s09_w5 SELECT * FROM orders WHERE id <= 100000;

-- (2) 容量：テーブル本体とインデックスの合計
SELECT c.relname,
       pg_size_pretty(pg_relation_size(c.oid)) AS heap,
       count(i.indexrelid) AS indexes,
       pg_size_pretty(coalesce(sum(pg_relation_size(i.indexrelid)), 0)) AS index_total
FROM pg_class c
LEFT JOIN pg_index i ON i.indrelid = c.oid
WHERE c.relname IN ('s09_w0', 's09_w2', 's09_w5')
GROUP BY c.oid, c.relname
ORDER BY c.relname;

-- (3) 同じ 1 万行の status を書き換える UPDATE。先に VACUUM して条件をそろえ、行数カウンタを 0 にする
VACUUM (ANALYZE) s09_w0, s09_w2, s09_w5;
SELECT pg_stat_reset_single_table_counters(oid) FROM pg_class WHERE relname IN ('s09_w0', 's09_w2', 's09_w5');
EXPLAIN (ANALYZE, TIMING OFF)
UPDATE s09_w0 SET status = CASE WHEN status = 'completed' THEN 'pending' ELSE 'completed' END WHERE id % 10 = 0;
EXPLAIN (ANALYZE, TIMING OFF)
UPDATE s09_w2 SET status = CASE WHEN status = 'completed' THEN 'pending' ELSE 'completed' END WHERE id % 10 = 0;
EXPLAIN (ANALYZE, TIMING OFF)
UPDATE s09_w5 SET status = CASE WHEN status = 'completed' THEN 'pending' ELSE 'completed' END WHERE id % 10 = 0;

-- (4) HOT 更新（インデックスを書き換えずに同じページへ新しい版を置く更新）の件数
--     変更行数の集計を先に書き出させてから見る
SELECT pg_stat_force_next_flush();
SELECT pg_sleep(1);
SELECT relname, n_tup_upd, n_tup_hot_upd
FROM pg_stat_user_tables
WHERE relname IN ('s09_w0', 's09_w2', 's09_w5')
ORDER BY relname;

-- (5) インデックスのある列でも「値が変わらない」更新なら HOT になる
--     (3) の更新でページの空きを使ったので、先に VACUUM して空きを戻してから試す
VACUUM s09_w5;
SELECT pg_stat_reset_single_table_counters('s09_w5'::regclass);
UPDATE s09_w5 SET status = status WHERE id % 10 = 1;
SELECT pg_stat_force_next_flush();
SELECT pg_sleep(1);
SELECT relname, n_tup_upd, n_tup_hot_upd
FROM pg_stat_user_tables
WHERE relname = 's09_w5';

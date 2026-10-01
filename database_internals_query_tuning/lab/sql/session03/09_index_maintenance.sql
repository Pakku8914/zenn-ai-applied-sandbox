-- セッション3-9: インデックスのメンテナンスコスト（書き込みのたびに B+木も更新される）
-- orders と同じ形の作業用テーブルを 3 つ作る。違いはインデックスの本数だけ
--   s03_ins_0 : インデックスなし
--   s03_ins_1 : ordered_at の 1 本
--   s03_ins_3 : ordered_at・customer_id・status の 3 本
DROP TABLE IF EXISTS s03_ins_0, s03_ins_1, s03_ins_3;
CREATE TABLE s03_ins_0 (LIKE orders);
CREATE TABLE s03_ins_1 (LIKE orders);
CREATE INDEX s03_ins_1_ordered_at_idx ON s03_ins_1 (ordered_at);
CREATE TABLE s03_ins_3 (LIKE orders);
CREATE INDEX s03_ins_3_ordered_at_idx  ON s03_ins_3 (ordered_at);
CREATE INDEX s03_ins_3_customer_id_idx ON s03_ins_3 (customer_id);
CREATE INDEX s03_ins_3_status_idx      ON s03_ins_3 (status);

-- 同じ 10 万行を入れる。EXPLAIN ANALYZE は実際に実行するので、行は本当に入る。
-- WAL: 変更の記録（ログ）の量。インデックスの更新も記録されるので、本数に応じて増える
EXPLAIN (ANALYZE, BUFFERS, WAL, COSTS OFF) INSERT INTO s03_ins_0 SELECT * FROM orders WHERE id <= 100000;
EXPLAIN (ANALYZE, BUFFERS, WAL, COSTS OFF) INSERT INTO s03_ins_1 SELECT * FROM orders WHERE id <= 100000;
EXPLAIN (ANALYZE, BUFFERS, WAL, COSTS OFF) INSERT INTO s03_ins_3 SELECT * FROM orders WHERE id <= 100000;

-- テーブル本体とインデックスの大きさ（ページ数）
SELECT t.relname AS tbl,
       pg_relation_size(t.oid) / 8192 AS table_pages,
       coalesce(i.relname, '-')       AS index_name,
       pg_relation_size(i.oid) / 8192 AS index_pages
FROM pg_class t
LEFT JOIN pg_index x ON x.indrelid = t.oid
LEFT JOIN pg_class i ON i.oid = x.indexrelid
WHERE t.relname IN ('s03_ins_0', 's03_ins_1', 's03_ins_3')
ORDER BY t.relname, i.relname;

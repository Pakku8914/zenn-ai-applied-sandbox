-- R03-06 インデックス設計と肥大化：更新される列にインデックスがあると HOT 更新にならない
-- \i sql/review03/06_hot_and_indexes.sql（数秒で終わる）
-- orders の先頭 20 万行を fillfactor 90（ページに 1 割の空き）で3つコピーし、インデックスの付け方だけを変える
--   r03_hot_pk     : 主キーだけ
--   r03_hot_date   : 主キー + ordered_at（更新しない列）のインデックス
--   r03_hot_status : 主キー + status（更新する列）のインデックス
SET client_min_messages = warning;
DROP TABLE IF EXISTS r03_hot_pk, r03_hot_date, r03_hot_status;
RESET client_min_messages;
CREATE TABLE r03_hot_pk (LIKE orders) WITH (autovacuum_enabled = off, fillfactor = 90);
CREATE TABLE r03_hot_date (LIKE orders) WITH (autovacuum_enabled = off, fillfactor = 90);
CREATE TABLE r03_hot_status (LIKE orders) WITH (autovacuum_enabled = off, fillfactor = 90);
INSERT INTO r03_hot_pk SELECT * FROM orders WHERE id <= 200000 ORDER BY id;
INSERT INTO r03_hot_date SELECT * FROM orders WHERE id <= 200000 ORDER BY id;
INSERT INTO r03_hot_status SELECT * FROM orders WHERE id <= 200000 ORDER BY id;
ALTER TABLE r03_hot_pk ADD PRIMARY KEY (id);
ALTER TABLE r03_hot_date ADD PRIMARY KEY (id);
ALTER TABLE r03_hot_status ADD PRIMARY KEY (id);
CREATE INDEX r03_hot_date_ordered_at_idx ON r03_hot_date (ordered_at);
CREATE INDEX r03_hot_status_status_idx ON r03_hot_status (status);
VACUUM (ANALYZE) r03_hot_pk, r03_hot_date, r03_hot_status;
-- 更新前のインデックスのページ数
SELECT indexrelname, pg_relation_size(indexrelid) / 8192 AS pages
FROM pg_stat_user_indexes
WHERE relname IN ('r03_hot_pk', 'r03_hot_date', 'r03_hot_status')
ORDER BY indexrelname;

-- 5% の注文を「保留」に変える（status だけを更新）
UPDATE r03_hot_pk SET status = 'pending' WHERE id % 20 = 0;
UPDATE r03_hot_date SET status = 'pending' WHERE id % 20 = 0;
UPDATE r03_hot_status SET status = 'pending' WHERE id % 20 = 0;
SELECT pg_stat_force_next_flush();

-- HOT 更新の数とテーブルのページ数
SELECT relname, n_tup_upd, n_tup_hot_upd, pg_relation_size(relid) / 8192 AS heap_pages
FROM pg_stat_user_tables
WHERE relname IN ('r03_hot_pk', 'r03_hot_date', 'r03_hot_status')
ORDER BY relname;
-- 更新後のインデックスごとのページ数
SELECT indexrelname, pg_relation_size(indexrelid) / 8192 AS pages
FROM pg_stat_user_indexes
WHERE relname IN ('r03_hot_pk', 'r03_hot_date', 'r03_hot_status')
ORDER BY indexrelname;
-- status のインデックスがあっても HOT になった行：もともと pending だった行（値が変わらない更新）
SELECT count(*) FILTER (WHERE status = 'pending') AS already_pending FROM orders WHERE id <= 200000 AND id % 20 = 0;

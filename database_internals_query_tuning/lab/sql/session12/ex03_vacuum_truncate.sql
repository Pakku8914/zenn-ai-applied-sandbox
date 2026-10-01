-- S12 演習: VACUUM でもファイルが小さくなるのはどんなときか（末尾のページが空になったときだけ）
-- \i sql/session12/ex03_vacuum_truncate.sql（数秒で終わる）
-- 行を id の順にページへ詰めるため、空の表に ORDER BY id で INSERT する（CREATE TABLE ... AS は末尾に空ページを余分に確保する）
SET client_min_messages = warning;
DROP TABLE IF EXISTS s12_tail;
RESET client_min_messages;
CREATE TABLE s12_tail (LIKE orders) WITH (autovacuum_enabled = off);
INSERT INTO s12_tail SELECT * FROM orders WHERE id <= 200000 ORDER BY id;
VACUUM s12_tail;
SELECT pg_relation_size('s12_tail') / 8192 AS heap_pages;

-- (1) 先頭側の 10 万行を消して VACUUM：空きはできるが末尾のページには行が残っているので、ページ数は変わらない
DELETE FROM s12_tail WHERE id <= 100000;
VACUUM (VERBOSE) s12_tail;
SELECT pg_relation_size('s12_tail') / 8192 AS heap_pages;

-- (2) 末尾側の 5 万行を消して VACUUM：末尾の空ページが切り詰められて（pages: N removed）ファイルが小さくなる
DELETE FROM s12_tail WHERE id > 150000;
VACUUM (VERBOSE) s12_tail;
SELECT pg_relation_size('s12_tail') / 8192 AS heap_pages;

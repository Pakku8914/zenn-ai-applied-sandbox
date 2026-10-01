-- 演習 S04-ex01: EXPLAIN と EXPLAIN ANALYZE、どちらが DELETE を実行するか
DROP TABLE IF EXISTS s04_ex01;
CREATE TABLE s04_ex01 AS SELECT * FROM products;
SELECT count(*) AS before FROM s04_ex01;

EXPLAIN DELETE FROM s04_ex01 WHERE category = '文具';
SELECT count(*) AS after_explain FROM s04_ex01;

EXPLAIN ANALYZE DELETE FROM s04_ex01 WHERE category = '文具';
SELECT count(*) AS after_explain_analyze FROM s04_ex01;

-- セッション4-3: EXPLAIN ANALYZE は「本当に実行する」
-- 作業用コピーで確かめる
DROP TABLE IF EXISTS s04_products;
CREATE TABLE s04_products AS SELECT * FROM products;
SELECT count(*) FROM s04_products;

-- EXPLAIN だけなら実行されない
EXPLAIN DELETE FROM s04_products WHERE id <= 100;
SELECT count(*) FROM s04_products;

-- EXPLAIN ANALYZE を付けると、DELETE が本当に実行される
EXPLAIN ANALYZE DELETE FROM s04_products WHERE id <= 100;
SELECT count(*) FROM s04_products;

-- 本物のテーブルで UPDATE / DELETE の計画を実測したいときは、トランザクションで包んで ROLLBACK する
BEGIN;
EXPLAIN ANALYZE UPDATE orders SET status = 'cancelled' WHERE id = 1;
SELECT id, status FROM orders WHERE id = 1;
ROLLBACK;
SELECT id, status FROM orders WHERE id = 1;

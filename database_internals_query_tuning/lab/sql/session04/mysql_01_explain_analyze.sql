-- セッション4（MySQL 比較）: MySQL の EXPLAIN / EXPLAIN ANALYZE（8.0.18 以降）
-- 先に tools/reset.sh で出発点に戻してから実行する
-- 使い方: docker compose exec -T lab mysql --skip-ssl -h mysql -ulab shopdb -t < sql/session04/mysql_01_explain_analyze.sql
CREATE INDEX idx_orders_ordered_at ON orders (ordered_at);
ANALYZE TABLE orders;

-- EXPLAIN FORMAT=TREE: 実行しない。見積もり（cost と rows）だけ
EXPLAIN FORMAT=TREE
SELECT o.id, c.name
FROM orders o
JOIN customers c ON c.id = o.customer_id
WHERE o.ordered_at >= '2025-06-01 10:00' AND o.ordered_at < '2025-06-01 11:00'\G

-- EXPLAIN ANALYZE: 実際に実行し、actual time（最初の行..最後の行）・rows・loops を並べる。
-- 内側（customers の主キー参照）の loops=116 は PostgreSQL の Nested Loop と同じ読み方
EXPLAIN ANALYZE
SELECT o.id, c.name
FROM orders o
JOIN customers c ON c.id = o.customer_id
WHERE o.ordered_at >= '2025-06-01 10:00' AND o.ordered_at < '2025-06-01 11:00'\G

-- UPDATE / DELETE の EXPLAIN ANALYZE は PostgreSQL と振る舞いが違う。作業用コピーで確かめる
DROP TABLE IF EXISTS s04_products;
CREATE TABLE s04_products AS SELECT * FROM products;

-- 1 テーブルの DELETE は EXPLAIN ANALYZE の対象外（実行されない）
EXPLAIN ANALYZE DELETE FROM s04_products WHERE id <= 100\G
SELECT count(*) FROM s04_products;

-- 複数テーブル形式の DELETE は計画どおりに実行されて actual が出るが、この版（9.7.2）では削除は残らなかった
EXPLAIN ANALYZE DELETE p FROM s04_products p JOIN products q ON q.id = p.id WHERE p.id <= 100\G
SELECT count(*) FROM s04_products;

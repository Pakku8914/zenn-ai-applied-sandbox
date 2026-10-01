-- S15-13 MySQL の実行計画の3つの表示形式（表形式・TREE・EXPLAIN ANALYZE）
-- docker compose exec -T lab mysql --skip-ssl -h mysql -ulab shopdb -t < sql/session15/13_mysql_explain_formats.sql
-- 題材：1週間の地域別の注文数と売上（キャンセル除外）。14_pg_explain_counterpart.sql と同じクエリ
CREATE INDEX orders_ordered_at_idx ON orders (ordered_at);

-- (1) 従来の表形式。1行が1つのテーブルへのアクセス。上の行ほど外側（先に読む）
EXPLAIN FORMAT=TRADITIONAL
SELECT c.region, COUNT(DISTINCT o.id) AS orders, SUM(oi.quantity * oi.unit_price) AS sales
FROM orders o
JOIN customers c ON c.id = o.customer_id
JOIN order_items oi ON oi.order_id = o.id
WHERE o.ordered_at >= '2025-06-01' AND o.ordered_at < '2025-06-08'
  AND o.status <> 'cancelled'
GROUP BY c.region
ORDER BY sales DESC;

-- (2) TREE 形式（MySQL 9 の EXPLAIN の既定）。PostgreSQL の EXPLAIN と同じく、字下げの深いほうが内側
EXPLAIN FORMAT=TREE
SELECT c.region, COUNT(DISTINCT o.id) AS orders, SUM(oi.quantity * oi.unit_price) AS sales
FROM orders o
JOIN customers c ON c.id = o.customer_id
JOIN order_items oi ON oi.order_id = o.id
WHERE o.ordered_at >= '2025-06-01' AND o.ordered_at < '2025-06-08'
  AND o.status <> 'cancelled'
GROUP BY c.region
ORDER BY sales DESC\G

-- (3) EXPLAIN ANALYZE：実際に実行して actual time / rows / loops を付ける
EXPLAIN ANALYZE
SELECT c.region, COUNT(DISTINCT o.id) AS orders, SUM(oi.quantity * oi.unit_price) AS sales
FROM orders o
JOIN customers c ON c.id = o.customer_id
JOIN order_items oi ON oi.order_id = o.id
WHERE o.ordered_at >= '2025-06-01' AND o.ordered_at < '2025-06-08'
  AND o.status <> 'cancelled'
GROUP BY c.region
ORDER BY sales DESC\G

-- (4) 結果
SELECT c.region, COUNT(DISTINCT o.id) AS orders, SUM(oi.quantity * oi.unit_price) AS sales
FROM orders o
JOIN customers c ON c.id = o.customer_id
JOIN order_items oi ON oi.order_id = o.id
WHERE o.ordered_at >= '2025-06-01' AND o.ordered_at < '2025-06-08'
  AND o.status <> 'cancelled'
GROUP BY c.region
ORDER BY sales DESC;

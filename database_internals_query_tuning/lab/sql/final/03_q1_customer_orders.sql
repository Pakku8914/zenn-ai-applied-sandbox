-- Final-03 Q1 顧客の注文一覧：総時間の 1 位。計画のどのノードで時間を使っているか
-- workload.py と同じ SQL の、パラメータに値（顧客 12345）を入れたもの
EXPLAIN (ANALYZE, BUFFERS)
SELECT o.id, o.ordered_at, o.status, count(*) AS items, sum(oi.quantity * oi.unit_price) AS amount
FROM orders o JOIN order_items oi ON oi.order_id = o.id
WHERE o.customer_id = 12345
GROUP BY o.id
ORDER BY o.ordered_at DESC
LIMIT 10;

-- 外部キーの列にインデックスがあるか。PostgreSQL は外部キー制約を張っても、参照する側の列にインデックスを作らない
SELECT c.conrelid::regclass AS table_name, c.conname, pg_get_constraintdef(c.oid) AS definition,
       EXISTS (SELECT 1 FROM pg_index i
               WHERE i.indrelid = c.conrelid AND i.indkey[0] = c.conkey[1]) AS has_index
FROM pg_constraint c
WHERE c.contype = 'f' AND c.conrelid IN ('orders'::regclass, 'order_items'::regclass)
ORDER BY 1, 2;

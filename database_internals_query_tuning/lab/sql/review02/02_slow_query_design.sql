-- Review02-02 遅いクエリ B：「顧客 777 の注文履歴（新しい順に 5 件と各注文の金額）」が 1 件の画面表示なのに数十 ms かかる

-- (1) 遅いクエリ B の実行計画（出発点の状態：主キーと外部キー制約だけ）
EXPLAIN (ANALYZE, BUFFERS)
SELECT o.id, o.ordered_at, sum(oi.quantity * oi.unit_price) AS amount
FROM orders o
JOIN order_items oi ON oi.order_id = o.id
WHERE o.customer_id = 777 AND o.status <> 'cancelled'
GROUP BY o.id, o.ordered_at
ORDER BY o.ordered_at DESC
LIMIT 5;

-- (2) 見積もりは合っている（rows と actual rows が近い）。足りないのは「顧客で引く道」と「注文から明細を引く道」
CREATE INDEX orders_customer_id_ordered_at_idx ON orders (customer_id, ordered_at);
CREATE INDEX order_items_order_id_idx ON order_items (order_id);

-- (3) インデックス追加後
EXPLAIN (ANALYZE, BUFFERS)
SELECT o.id, o.ordered_at, sum(oi.quantity * oi.unit_price) AS amount
FROM orders o
JOIN order_items oi ON oi.order_id = o.id
WHERE o.customer_id = 777 AND o.status <> 'cancelled'
GROUP BY o.id, o.ordered_at
ORDER BY o.ordered_at DESC
LIMIT 5;

-- (4) 結果
SELECT o.id, o.ordered_at, sum(oi.quantity * oi.unit_price) AS amount
FROM orders o
JOIN order_items oi ON oi.order_id = o.id
WHERE o.customer_id = 777 AND o.status <> 'cancelled'
GROUP BY o.id, o.ordered_at
ORDER BY o.ordered_at DESC
LIMIT 5;

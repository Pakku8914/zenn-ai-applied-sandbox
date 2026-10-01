-- Review02-03 遅いクエリ C：統計は正しく、インデックスもある。それでも速い方式が選ばれない
-- 「2025年3月1日〜7日の『文具』の売上」。02 で order_items(order_id) のインデックスを作ってある（無ければ作る）
CREATE INDEX IF NOT EXISTS order_items_order_id_idx ON order_items (order_id);
-- 02 で作った (customer_id, ordered_at) の複合インデックスは、このクエリの比較を読みにくくする
-- （random_page_cost を下げると PostgreSQL 18 のスキップスキャンで ordered_at の範囲検索に使われる）ので消しておく
DROP INDEX IF EXISTS orders_customer_id_ordered_at_idx;
SET max_parallel_workers_per_gather = 0;

-- (1) 既定：Hash Join。rows と actual rows はどのノードでも近い
EXPLAIN (ANALYZE, BUFFERS)
SELECT sum(oi.quantity * oi.unit_price) AS sales, count(*) AS lines
FROM orders o
JOIN order_items oi ON oi.order_id = o.id
JOIN products p ON p.id = oi.product_id
WHERE o.ordered_at >= '2025-03-01' AND o.ordered_at < '2025-03-08'
  AND o.status <> 'cancelled'
  AND p.category = '文具';

-- (2) 比較：Nested Loop だけを許すと速い
SET enable_hashjoin = off;
SET enable_mergejoin = off;
EXPLAIN (ANALYZE, BUFFERS)
SELECT sum(oi.quantity * oi.unit_price) AS sales, count(*) AS lines
FROM orders o
JOIN order_items oi ON oi.order_id = o.id
JOIN products p ON p.id = oi.product_id
WHERE o.ordered_at >= '2025-03-01' AND o.ordered_at < '2025-03-08'
  AND o.status <> 'cancelled'
  AND p.category = '文具';
RESET enable_hashjoin;
RESET enable_mergejoin;

-- (3) プランナの前提を確かめる：ランダム読み 1 ページのコストは順次読みの 4 倍（ディスクを想定した既定値）
SHOW seq_page_cost;
SHOW random_page_cost;

-- (4) このセッションだけ「ランダム読みも安い（データはほぼキャッシュにある）」と教えると、プランナは自分で Nested Loop を選ぶ。
--     コスト定数の調整は S14 で扱う。ここでは「原因の切り分け」のための実験で、設定の推奨値ではない
SET random_page_cost = 1.1;
EXPLAIN (ANALYZE, BUFFERS)
SELECT sum(oi.quantity * oi.unit_price) AS sales, count(*) AS lines
FROM orders o
JOIN order_items oi ON oi.order_id = o.id
JOIN products p ON p.id = oi.product_id
WHERE o.ordered_at >= '2025-03-01' AND o.ordered_at < '2025-03-08'
  AND o.status <> 'cancelled'
  AND p.category = '文具';

RESET random_page_cost;
RESET max_parallel_workers_per_gather;

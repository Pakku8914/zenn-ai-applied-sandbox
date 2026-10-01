-- Review02-01 遅いクエリ A：「当日の顧客別売上トップ 10」が 1 秒かかる
-- 先に出発点へ戻しておく: docker compose exec lab bash tools/reset.sh
-- 日次バッチが作業用テーブル r02_daily_orders / r02_daily_items に当日分（2025-12-01）を追記した直後に実行した、という場面。
-- 統計の古さを再現するため autovacuum を止めてある（前日分を入れた時点で ANALYZE 済み）

DROP TABLE IF EXISTS r02_daily_items, r02_daily_orders;
CREATE TABLE r02_daily_orders (
    batch_date date NOT NULL, order_id bigint NOT NULL, customer_id integer NOT NULL, status text NOT NULL
) WITH (autovacuum_enabled = false);
CREATE TABLE r02_daily_items (
    batch_date date NOT NULL, order_id bigint NOT NULL, product_id integer NOT NULL,
    quantity integer NOT NULL, unit_price integer NOT NULL
) WITH (autovacuum_enabled = false);

-- 前日（2025-11-30）分：投入して ANALYZE
INSERT INTO r02_daily_orders
SELECT ordered_at::date, id, customer_id, status FROM orders
WHERE ordered_at >= '2025-11-30' AND ordered_at < '2025-12-01';
INSERT INTO r02_daily_items
SELECT o.ordered_at::date, oi.order_id, oi.product_id, oi.quantity, oi.unit_price
FROM order_items oi JOIN orders o ON o.id = oi.order_id
WHERE o.ordered_at >= '2025-11-30' AND o.ordered_at < '2025-12-01';
ANALYZE r02_daily_orders, r02_daily_items;

-- 当日（2025-12-01）分：追記しただけ
INSERT INTO r02_daily_orders
SELECT ordered_at::date, id, customer_id, status FROM orders
WHERE ordered_at >= '2025-12-01' AND ordered_at < '2025-12-02';
INSERT INTO r02_daily_items
SELECT o.ordered_at::date, oi.order_id, oi.product_id, oi.quantity, oi.unit_price
FROM order_items oi JOIN orders o ON o.id = oi.order_id
WHERE o.ordered_at >= '2025-12-01' AND o.ordered_at < '2025-12-02';

-- (1) 遅いクエリ A の実行計画
EXPLAIN (ANALYZE, BUFFERS)
SELECT c.region, o.customer_id, sum(i.quantity * i.unit_price) AS sales
FROM r02_daily_orders o
JOIN r02_daily_items i ON i.order_id = o.order_id
JOIN customers c ON c.id = o.customer_id
WHERE o.batch_date = '2025-12-01' AND i.batch_date = '2025-12-01'
  AND o.status <> 'cancelled'
GROUP BY c.region, o.customer_id
ORDER BY sales DESC, o.customer_id
LIMIT 10;

-- (2) 容疑者 1「ソートが重いのでは」：work_mem を 8 倍にしても計画も時間も変わらない
SET work_mem = '64MB';
EXPLAIN (ANALYZE, BUFFERS)
SELECT c.region, o.customer_id, sum(i.quantity * i.unit_price) AS sales
FROM r02_daily_orders o
JOIN r02_daily_items i ON i.order_id = o.order_id
JOIN customers c ON c.id = o.customer_id
WHERE o.batch_date = '2025-12-01' AND i.batch_date = '2025-12-01'
  AND o.status <> 'cancelled'
GROUP BY c.region, o.customer_id
ORDER BY sales DESC, o.customer_id
LIMIT 10;
RESET work_mem;

-- (3) 容疑者 2「統計が古いのでは」：統計が知っている batch_date は前日の値だけ
SELECT tablename, attname, n_distinct, most_common_vals, most_common_freqs
FROM pg_stats
WHERE tablename IN ('r02_daily_orders', 'r02_daily_items') AND attname = 'batch_date'
ORDER BY tablename;

-- (4) 統計を取り直すと、プランナは自分で Hash Join を選ぶ
ANALYZE r02_daily_orders, r02_daily_items;
EXPLAIN (ANALYZE, BUFFERS)
SELECT c.region, o.customer_id, sum(i.quantity * i.unit_price) AS sales
FROM r02_daily_orders o
JOIN r02_daily_items i ON i.order_id = o.order_id
JOIN customers c ON c.id = o.customer_id
WHERE o.batch_date = '2025-12-01' AND i.batch_date = '2025-12-01'
  AND o.status <> 'cancelled'
GROUP BY c.region, o.customer_id
ORDER BY sales DESC, o.customer_id
LIMIT 10;

-- (5) 結果（ANALYZE の前後で同じ）
SELECT c.region, o.customer_id, sum(i.quantity * i.unit_price) AS sales
FROM r02_daily_orders o
JOIN r02_daily_items i ON i.order_id = o.order_id
JOIN customers c ON c.id = o.customer_id
WHERE o.batch_date = '2025-12-01' AND i.batch_date = '2025-12-01'
  AND o.status <> 'cancelled'
GROUP BY c.region, o.customer_id
ORDER BY sales DESC, o.customer_id
LIMIT 10;

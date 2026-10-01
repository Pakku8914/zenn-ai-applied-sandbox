-- S07-06 見積もりが外れて Nested Loop が選ばれ、破滅的に遅くなる
-- 場面：日次バッチが作業用テーブルに「当日分」を追記した直後、ANALYZE が走る前に集計を実行した
-- 作業用テーブルは s07_ 接頭辞。autovacuum を止めて「統計が前日のまま」の状態を再現する
-- （autovacuum が有効だと、この環境（autovacuum_naptime = 10s）では自動 ANALYZE が先に走り、再現しないことがある）

DROP TABLE IF EXISTS s07_stage_items, s07_stage_orders;
CREATE TABLE s07_stage_orders (
    batch_date  date    NOT NULL,
    order_id    bigint  NOT NULL,
    customer_id integer NOT NULL,
    status      text    NOT NULL
) WITH (autovacuum_enabled = false);
CREATE TABLE s07_stage_items (
    batch_date  date    NOT NULL,
    order_id    bigint  NOT NULL,
    product_id  integer NOT NULL,
    quantity    integer NOT NULL,
    unit_price  integer NOT NULL
) WITH (autovacuum_enabled = false);

-- 前日（2025-12-30）分を投入して ANALYZE する（ここまでは正常な運用）
INSERT INTO s07_stage_orders
SELECT ordered_at::date, id, customer_id, status FROM orders
WHERE ordered_at >= '2025-12-30' AND ordered_at < '2025-12-31';
INSERT INTO s07_stage_items
SELECT o.ordered_at::date, oi.order_id, oi.product_id, oi.quantity, oi.unit_price
FROM order_items oi JOIN orders o ON o.id = oi.order_id
WHERE o.ordered_at >= '2025-12-30' AND o.ordered_at < '2025-12-31';
ANALYZE s07_stage_orders, s07_stage_items;

-- 当日（2025-12-31）分を追記する。ANALYZE はまだ走っていない
INSERT INTO s07_stage_orders
SELECT ordered_at::date, id, customer_id, status FROM orders
WHERE ordered_at >= '2025-12-31' AND ordered_at < '2026-01-01';
INSERT INTO s07_stage_items
SELECT o.ordered_at::date, oi.order_id, oi.product_id, oi.quantity, oi.unit_price
FROM order_items oi JOIN orders o ON o.id = oi.order_id
WHERE o.ordered_at >= '2025-12-31' AND o.ordered_at < '2026-01-01';

-- (1) 統計が知っている batch_date は前日の値だけ
SELECT tablename, attname, n_distinct, most_common_vals, most_common_freqs
FROM pg_stats
WHERE tablename IN ('s07_stage_orders', 's07_stage_items') AND attname = 'batch_date'
ORDER BY tablename;

-- (2) 当日分の売上を集計する：両側とも rows=1 と見積もられ、Nested Loop が選ばれる
EXPLAIN (ANALYZE, BUFFERS)
SELECT sum(i.quantity * i.unit_price) AS sales, count(*) AS lines
FROM s07_stage_orders o
JOIN s07_stage_items i ON i.order_id = o.order_id
WHERE o.batch_date = '2025-12-31' AND i.batch_date = '2025-12-31'
  AND o.status <> 'cancelled';

-- (3) 比較用：統計はそのままで Nested Loop だけを禁止する
SET enable_nestloop = off;
EXPLAIN (ANALYZE, BUFFERS)
SELECT sum(i.quantity * i.unit_price) AS sales, count(*) AS lines
FROM s07_stage_orders o
JOIN s07_stage_items i ON i.order_id = o.order_id
WHERE o.batch_date = '2025-12-31' AND i.batch_date = '2025-12-31'
  AND o.status <> 'cancelled';
RESET enable_nestloop;

-- (4) 本当の直し方：統計を取り直す
ANALYZE s07_stage_orders, s07_stage_items;
EXPLAIN (ANALYZE, BUFFERS)
SELECT sum(i.quantity * i.unit_price) AS sales, count(*) AS lines
FROM s07_stage_orders o
JOIN s07_stage_items i ON i.order_id = o.order_id
WHERE o.batch_date = '2025-12-31' AND i.batch_date = '2025-12-31'
  AND o.status <> 'cancelled';

-- (5) 結果（どのプランでも同じ）
SELECT sum(i.quantity * i.unit_price) AS sales, count(*) AS lines
FROM s07_stage_orders o
JOIN s07_stage_items i ON i.order_id = o.order_id
WHERE o.batch_date = '2025-12-31' AND i.batch_date = '2025-12-31'
  AND o.status <> 'cancelled';

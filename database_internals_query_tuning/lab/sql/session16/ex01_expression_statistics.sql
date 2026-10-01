-- S16 演習：日次集計の見積もりを直す（式の統計）
-- 先に出発点へ戻しておく: docker compose exec lab bash tools/reset.sh
-- 日付に変換した式の値の種類数をプランナは知らないので、グループ数を行数と同じ 100 万と見積もる

-- (1) 見積もり rows と actual rows を見比べる
SET max_parallel_workers_per_gather = 0;
EXPLAIN (ANALYZE, BUFFERS)
SELECT (ordered_at AT TIME ZONE 'UTC')::date AS day, count(*)
FROM orders
GROUP BY day;

-- (2) 式に統計を取らせる（PostgreSQL 14 以降）
CREATE STATISTICS s16_orders_day_stats ON ((ordered_at AT TIME ZONE 'UTC')::date) FROM orders;
ANALYZE orders;
EXPLAIN (ANALYZE, BUFFERS)
SELECT (ordered_at AT TIME ZONE 'UTC')::date AS day, count(*)
FROM orders
GROUP BY day;

-- (3) 09_materialized_view.sql の (1)（order_items と結合する日次売上）も、見積もりが変わると計画が変わるか
EXPLAIN (ANALYZE, BUFFERS)
SELECT (o.ordered_at AT TIME ZONE 'UTC')::date AS day,
       sum(oi.quantity * oi.unit_price) AS sales, count(*) AS lines
FROM orders o JOIN order_items oi ON oi.order_id = o.id
WHERE o.status <> 'cancelled'
GROUP BY day
ORDER BY day;
RESET max_parallel_workers_per_gather;

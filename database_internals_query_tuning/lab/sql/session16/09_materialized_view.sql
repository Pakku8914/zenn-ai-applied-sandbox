-- S16-09 集計テーブル（マテリアライズドビュー）：日次売上をあらかじめ計算しておく
-- 先に出発点へ戻しておく: docker compose exec lab bash tools/reset.sh

-- (1) 元の集計：1年分の日次売上（キャンセル除外）。毎回 orders と order_items を全部読む
EXPLAIN (ANALYZE, BUFFERS)
SELECT (o.ordered_at AT TIME ZONE 'UTC')::date AS day,
       sum(oi.quantity * oi.unit_price) AS sales, count(*) AS lines
FROM orders o JOIN order_items oi ON oi.order_id = o.id
WHERE o.status <> 'cancelled'
GROUP BY day
ORDER BY day;

-- (2) 同じ集計をマテリアライズドビューとして保存する（結果の 365 行だけが残る）
DROP MATERIALIZED VIEW IF EXISTS s16_daily_sales;
CREATE MATERIALIZED VIEW s16_daily_sales AS
SELECT (o.ordered_at AT TIME ZONE 'UTC')::date AS day,
       sum(oi.quantity * oi.unit_price) AS sales, count(*) AS lines
FROM orders o JOIN order_items oi ON oi.order_id = o.id
WHERE o.status <> 'cancelled'
GROUP BY day;
ANALYZE s16_daily_sales;
SELECT count(*) AS days, pg_relation_size('s16_daily_sales') / 8192 AS pages FROM s16_daily_sales;

-- (3) 読むのは保存した結果だけ
EXPLAIN (ANALYZE, BUFFERS)
SELECT day, sales, lines FROM s16_daily_sales ORDER BY day;

-- (4) 中身は作った時点のまま。元の表が変わっても、REFRESH するまで反映されない
SELECT day, sales, lines FROM s16_daily_sales WHERE day = '2025-06-01';

-- (5) 作り直す（REFRESH）。既定では作り直しの間、ビューを読む側も待たされる（ACCESS EXCLUSIVE ロック）
\timing on
REFRESH MATERIALIZED VIEW s16_daily_sales;
\timing off

-- (6) 読む側を止めない CONCURRENTLY には、一意インデックスが要る
REFRESH MATERIALIZED VIEW CONCURRENTLY s16_daily_sales;
CREATE UNIQUE INDEX s16_daily_sales_day_idx ON s16_daily_sales (day);
\timing on
REFRESH MATERIALIZED VIEW CONCURRENTLY s16_daily_sales;
\timing off

-- Final-ex06 Q5 を集計テーブル（マテリアライズドビュー）にすると：読むのは一瞬だが、作り直しの時間と「鮮度」の問題が残る
-- 1 分ほどかかる（最後に片付ける）
SET client_min_messages = warning;
DROP MATERIALIZED VIEW IF EXISTS final_daily_sales;
RESET client_min_messages;
-- 1 年分の日別売上と購入者数（Q5 と同じ集計を全期間で）
CREATE MATERIALIZED VIEW final_daily_sales AS
SELECT date_trunc('day', o.ordered_at) AS day,
       count(DISTINCT o.customer_id) AS buyers,
       sum(oi.quantity * oi.unit_price) AS sales
FROM orders o JOIN order_items oi ON oi.order_id = o.id
WHERE o.status <> 'cancelled'
GROUP BY 1;
-- CONCURRENTLY（読み取りを止めない作り直し）には一意インデックスが必要
CREATE UNIQUE INDEX final_daily_sales_day_idx ON final_daily_sales (day);

-- (1) 作り直しにかかる時間。通常の REFRESH は作り直しの間、ビューの読み取りを止める（ACCESS EXCLUSIVE）
\timing on
REFRESH MATERIALIZED VIEW final_daily_sales;
REFRESH MATERIALIZED VIEW CONCURRENTLY final_daily_sales;
\timing off

-- (2) 画面からは、ビューの 90 日分を読むだけになる
EXPLAIN (ANALYZE, BUFFERS)
SELECT day, buyers, sales FROM final_daily_sales
WHERE day >= '2025-10-03' AND day < '2026-01-01'
ORDER BY day;

-- (3) 結果が Q5 と一致するか（食い違う日数）
SELECT count(*) AS mismatched_days
FROM (SELECT date_trunc('day', o.ordered_at) AS day, count(DISTINCT o.customer_id) AS buyers,
             sum(oi.quantity * oi.unit_price) AS sales
      FROM orders o JOIN order_items oi ON oi.order_id = o.id
      WHERE o.status <> 'cancelled' AND o.ordered_at >= '2025-10-03' AND o.ordered_at < '2026-01-01'
      GROUP BY 1) q
FULL JOIN (SELECT * FROM final_daily_sales WHERE day >= '2025-10-03' AND day < '2026-01-01') m USING (day)
WHERE q.sales IS DISTINCT FROM m.sales OR q.buyers IS DISTINCT FROM m.buyers;

-- 片付け
DROP MATERIALIZED VIEW final_daily_sales;

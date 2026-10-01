-- Final-ex05 orders を月ごとのパーティションに分ければ Q5 は速くなるか（作業用コピー final_orders_part で試す）
-- 20 秒ほどかかり、ディスクを 100MB ほど使う（最後に片付ける）
SET client_min_messages = warning;
DROP TABLE IF EXISTS final_orders_part;
RESET client_min_messages;
CREATE TABLE final_orders_part (LIKE orders) PARTITION BY RANGE (ordered_at);
DO $$
BEGIN
  FOR m IN 1..12 LOOP
    EXECUTE format('CREATE TABLE final_orders_part_%s PARTITION OF final_orders_part FOR VALUES FROM (%L) TO (%L)',
                   lpad(m::text, 2, '0'),
                   make_timestamptz(2025, m, 1, 0, 0, 0, 'UTC'),
                   make_timestamptz(2025, 1, 1, 0, 0, 0, 'UTC') + make_interval(months => m));
  END LOOP;
END $$;
INSERT INTO final_orders_part SELECT * FROM orders ORDER BY id;
-- パーティションにした表の主キーには、パーティションキー（ordered_at）を含めなければならない
ALTER TABLE final_orders_part ADD PRIMARY KEY (id, ordered_at);
VACUUM (ANALYZE) final_orders_part;

-- (1) 計画：orders 側は 10〜12 月の 3 つのパーティションだけを読む。order_items 側は変わらず全件
EXPLAIN (ANALYZE, BUFFERS)
SELECT date_trunc('day', o.ordered_at) AS day, count(DISTINCT o.customer_id) AS buyers,
       sum(oi.quantity * oi.unit_price) AS sales
FROM final_orders_part o JOIN order_items oi ON oi.order_id = o.id
WHERE o.status <> 'cancelled' AND o.ordered_at >= '2025-10-03' AND o.ordered_at < '2026-01-01'
GROUP BY 1 ORDER BY 1;

-- (2) 交互に 5 回ずつ：元の orders と、パーティションにしたコピー
CREATE OR REPLACE FUNCTION pg_temp.final_exec_ms(q text) RETURNS numeric
LANGUAGE plpgsql AS $$
DECLARE j json;
BEGIN
  EXECUTE 'EXPLAIN (ANALYZE, TIMING OFF, FORMAT JSON) ' || q INTO j;
  RETURN round((j -> 0 ->> 'Execution Time')::numeric, 3);
END $$;
DROP TABLE IF EXISTS pg_temp.final_ex05;
CREATE TEMP TABLE final_ex05 (variant text, round int, ms numeric);
DO $$
DECLARE
  q5 text := $q$SELECT date_trunc('day', o.ordered_at) AS day, count(DISTINCT o.customer_id) AS buyers,
                       sum(oi.quantity * oi.unit_price) AS sales
                FROM %s o JOIN order_items oi ON oi.order_id = o.id
                WHERE o.status <> 'cancelled' AND o.ordered_at >= '2025-10-03' AND o.ordered_at < '2026-01-01'
                GROUP BY 1 ORDER BY 1$q$;
BEGIN
  PERFORM pg_temp.final_exec_ms(format(q5, 'final_orders_part'));
  FOR r IN 1..5 LOOP
    INSERT INTO final_ex05 VALUES ('orders（そのまま）', r, pg_temp.final_exec_ms(format(q5, 'orders')));
    INSERT INTO final_ex05 VALUES ('月ごとのパーティション', r, pg_temp.final_exec_ms(format(q5, 'final_orders_part')));
  END LOOP;
END $$;
SELECT variant, percentile_cont(0.5) WITHIN GROUP (ORDER BY ms) AS median_ms, min(ms) AS min_ms, max(ms) AS max_ms
FROM final_ex05 GROUP BY variant ORDER BY variant;

-- 片付け
DROP TABLE final_orders_part;

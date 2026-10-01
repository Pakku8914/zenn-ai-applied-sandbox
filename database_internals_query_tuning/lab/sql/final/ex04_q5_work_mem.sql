-- Final-ex04 Q5 は work_mem を上げれば直るか：8MB（このサンドボックスの設定）と 64MB を交互に 5 回ずつ測る
-- work_mem はこのセッションの中だけで変える（set_config の第 3 引数 true = トランザクションの中だけ）。
-- work_mem はソート・ハッシュのノードごと・並列ワーカーごとに確保されるので、むやみに大きくしない（ここでは 64MB まで）
CREATE OR REPLACE FUNCTION pg_temp.final_exec_ms_wm(q text, wm text) RETURNS numeric
LANGUAGE plpgsql AS $$
DECLARE j json;
BEGIN
  PERFORM set_config('work_mem', wm, true);
  EXECUTE 'EXPLAIN (ANALYZE, TIMING OFF, FORMAT JSON) ' || q INTO j;
  PERFORM set_config('work_mem', '8MB', true);
  RETURN round((j -> 0 ->> 'Execution Time')::numeric, 3);
END $$;

DROP TABLE IF EXISTS pg_temp.final_ex04;
CREATE TEMP TABLE final_ex04 (variant text, round int, ms numeric);
DO $$
DECLARE
  q5 text := $q$SELECT date_trunc('day', o.ordered_at) AS day, count(DISTINCT o.customer_id) AS buyers,
                       sum(oi.quantity * oi.unit_price) AS sales
                FROM orders o JOIN order_items oi ON oi.order_id = o.id
                WHERE o.status <> 'cancelled' AND o.ordered_at >= '2025-10-03' AND o.ordered_at < '2026-01-01'
                GROUP BY 1 ORDER BY 1$q$;
BEGIN
  PERFORM pg_temp.final_exec_ms_wm(q5, '8MB');
  FOR r IN 1..5 LOOP
    INSERT INTO final_ex04 VALUES ('work_mem = 8MB', r, pg_temp.final_exec_ms_wm(q5, '8MB'));
    INSERT INTO final_ex04 VALUES ('work_mem = 64MB', r, pg_temp.final_exec_ms_wm(q5, '64MB'));
  END LOOP;
END $$;
SELECT variant, percentile_cont(0.5) WITHIN GROUP (ORDER BY ms) AS median_ms, min(ms) AS min_ms, max(ms) AS max_ms
FROM final_ex04 GROUP BY variant ORDER BY variant;

-- 64MB のときの計画：ソートはメモリに収まる（quicksort）が、並列（Gather Merge）をやめている
SET work_mem = '64MB';
EXPLAIN (ANALYZE, BUFFERS)
SELECT date_trunc('day', o.ordered_at) AS day, count(DISTINCT o.customer_id) AS buyers,
       sum(oi.quantity * oi.unit_price) AS sales
FROM orders o JOIN order_items oi ON oi.order_id = o.id
WHERE o.status <> 'cancelled' AND o.ordered_at >= '2025-10-03' AND o.ordered_at < '2026-01-01'
GROUP BY 1 ORDER BY 1;
RESET work_mem;

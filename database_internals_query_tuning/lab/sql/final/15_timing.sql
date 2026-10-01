-- Final-15 1 本ずつの改善前後を「交互に 5 回ずつ」測り、中央値と倍率を表にする（インデックスで直した Q1・Q4 と、直さない Q5）
-- 10 の後に実行する。改善前の計画は、10 で足したインデックスをサブトランザクションの中で DROP INDEX して作り、
-- 測り終えたらそのサブトランザクションを取り消す（インデックスは消えずに残る）。10 秒ほどかかる
-- 時間は EXPLAIN (ANALYZE, TIMING OFF) の Execution Time。環境によって変わるので、倍率で比べる
CREATE OR REPLACE FUNCTION pg_temp.final_exec_ms(q text) RETURNS numeric
LANGUAGE plpgsql AS $$
DECLARE j json;
BEGIN
  EXECUTE 'EXPLAIN (ANALYZE, TIMING OFF, FORMAT JSON) ' || q INTO j;
  RETURN round((j -> 0 ->> 'Execution Time')::numeric, 3);
END $$;

-- 10 のインデックスがない状態で 1 回実行する。例外でサブトランザクションを取り消し、DROP INDEX をなかったことにする
CREATE OR REPLACE FUNCTION pg_temp.final_exec_ms_before(q text) RETURNS numeric
LANGUAGE plpgsql AS $$
DECLARE ms numeric;
BEGIN
  BEGIN
    DROP INDEX orders_customer_id_idx, order_items_order_id_idx;
    ms := pg_temp.final_exec_ms(q);
    RAISE EXCEPTION 'undo';
  EXCEPTION WHEN raise_exception THEN
    NULL;
  END;
  RETURN ms;
END $$;

DROP TABLE IF EXISTS pg_temp.final_timing;
CREATE TEMP TABLE final_timing (query text, variant text, round int, ms numeric);

DO $$
DECLARE
  q1 text := $q$SELECT o.id, o.ordered_at, o.status, count(*) AS items, sum(oi.quantity * oi.unit_price) AS amount
                FROM orders o JOIN order_items oi ON oi.order_id = o.id
                WHERE o.customer_id = 12345 GROUP BY o.id ORDER BY o.ordered_at DESC LIMIT 10$q$;
  q4 text := $q$SELECT p.id, p.name, sum(oi.quantity) AS qty, sum(oi.quantity * oi.unit_price) AS sales
                FROM orders o JOIN order_items oi ON oi.order_id = o.id JOIN products p ON p.id = oi.product_id
                WHERE o.ordered_at >= '2025-12-25' AND o.ordered_at < '2026-01-01'
                  AND o.status <> 'cancelled' AND p.category = '文具'
                GROUP BY p.id, p.name ORDER BY sales DESC LIMIT 10$q$;
  q5 text := $q$SELECT date_trunc('day', o.ordered_at) AS day, count(DISTINCT o.customer_id) AS buyers,
                       sum(oi.quantity * oi.unit_price) AS sales
                FROM orders o JOIN order_items oi ON oi.order_id = o.id
                WHERE o.status <> 'cancelled' AND o.ordered_at >= '2025-10-03' AND o.ordered_at < '2026-01-01'
                GROUP BY 1 ORDER BY 1$q$;
BEGIN
  -- 空回し（キャッシュを温める。記録しない）
  PERFORM pg_temp.final_exec_ms(q1), pg_temp.final_exec_ms_before(q1),
          pg_temp.final_exec_ms(q4), pg_temp.final_exec_ms_before(q4);
  FOR r IN 1..5 LOOP
    INSERT INTO final_timing VALUES ('Q1', '改善前', r, pg_temp.final_exec_ms_before(q1));
    INSERT INTO final_timing VALUES ('Q1', '改善後', r, pg_temp.final_exec_ms(q1));
    INSERT INTO final_timing VALUES ('Q4', '改善前', r, pg_temp.final_exec_ms_before(q4));
    INSERT INTO final_timing VALUES ('Q4', '改善後', r, pg_temp.final_exec_ms(q4));
    INSERT INTO final_timing VALUES ('Q5', '改善前', r, pg_temp.final_exec_ms_before(q5));
    INSERT INTO final_timing VALUES ('Q5', '改善後', r, pg_temp.final_exec_ms(q5));
  END LOOP;
END $$;

SELECT query,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY ms) FILTER (WHERE variant = '改善前') AS before_ms,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY ms) FILTER (WHERE variant = '改善後') AS after_ms,
       round((percentile_cont(0.5) WITHIN GROUP (ORDER BY ms) FILTER (WHERE variant = '改善前')
            / percentile_cont(0.5) WITHIN GROUP (ORDER BY ms) FILTER (WHERE variant = '改善後'))::numeric, 1) AS ratio
FROM final_timing
GROUP BY query
ORDER BY query;

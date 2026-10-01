-- Final-ex03 orders (ordered_at) のインデックスは入れるべきか：Q4 は速くなるが、Q5 の計画が変わる
-- 10 の後に実行する。orders_ordered_at_idx を作り、「あり」と「なし（サブトランザクションで DROP して取り消す）」を交互に 5 回ずつ測る。
-- 最後に消す（10 の設計には入れない）
CREATE INDEX orders_ordered_at_idx ON orders (ordered_at);
ANALYZE orders;
CREATE OR REPLACE FUNCTION pg_temp.final_exec_ms(q text) RETURNS numeric
LANGUAGE plpgsql AS $$
DECLARE j json;
BEGIN
  EXECUTE 'EXPLAIN (ANALYZE, TIMING OFF, FORMAT JSON) ' || q INTO j;
  RETURN round((j -> 0 ->> 'Execution Time')::numeric, 3);
END $$;

-- orders_ordered_at_idx だけがない状態で 1 回実行する（計画の形も返す）
CREATE OR REPLACE FUNCTION pg_temp.final_exec_ms_without_ordered_at(q text) RETURNS numeric
LANGUAGE plpgsql AS $$
DECLARE ms numeric;
BEGIN
  BEGIN
    DROP INDEX orders_ordered_at_idx;
    ms := pg_temp.final_exec_ms(q);
    RAISE EXCEPTION 'undo';
  EXCEPTION WHEN raise_exception THEN
    NULL;
  END;
  RETURN ms;
END $$;

DROP TABLE IF EXISTS pg_temp.final_ex03;
CREATE TEMP TABLE final_ex03 (query text, variant text, round int, ms numeric);

DO $$
DECLARE
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
  PERFORM pg_temp.final_exec_ms(q4), pg_temp.final_exec_ms_without_ordered_at(q4);
  FOR r IN 1..5 LOOP
    INSERT INTO final_ex03 VALUES ('Q4', 'ordered_at あり', r, pg_temp.final_exec_ms(q4));
    INSERT INTO final_ex03 VALUES ('Q4', 'ordered_at なし', r, pg_temp.final_exec_ms_without_ordered_at(q4));
    INSERT INTO final_ex03 VALUES ('Q5', 'ordered_at あり', r, pg_temp.final_exec_ms(q5));
    INSERT INTO final_ex03 VALUES ('Q5', 'ordered_at なし', r, pg_temp.final_exec_ms_without_ordered_at(q5));
  END LOOP;
END $$;

SELECT query, variant, percentile_cont(0.5) WITHIN GROUP (ORDER BY ms) AS median_ms
FROM final_ex03
GROUP BY query, variant
ORDER BY query, variant;

-- workload.py の 1,000 操作あたりの回数（Q4 80 回・Q5 20 回）で掛けて、総実行時間がどれだけ変わるかを見積もる
SELECT round(80 * (percentile_cont(0.5) WITHIN GROUP (ORDER BY ms) FILTER (WHERE query = 'Q4' AND variant = 'ordered_at あり')
                 - percentile_cont(0.5) WITHIN GROUP (ORDER BY ms) FILTER (WHERE query = 'Q4' AND variant = 'ordered_at なし'))::numeric) AS q4_change_ms,
       round(20 * (percentile_cont(0.5) WITHIN GROUP (ORDER BY ms) FILTER (WHERE query = 'Q5' AND variant = 'ordered_at あり')
                 - percentile_cont(0.5) WITHIN GROUP (ORDER BY ms) FILTER (WHERE query = 'Q5' AND variant = 'ordered_at なし'))::numeric) AS q5_change_ms
FROM final_ex03;

-- 計画の形の違い。まず orders_ordered_at_idx がある状態（Q5 → Q4）
EXPLAIN (COSTS OFF)
SELECT date_trunc('day', o.ordered_at) AS day, count(DISTINCT o.customer_id) AS buyers,
       sum(oi.quantity * oi.unit_price) AS sales
FROM orders o JOIN order_items oi ON oi.order_id = o.id
WHERE o.status <> 'cancelled' AND o.ordered_at >= '2025-10-03' AND o.ordered_at < '2026-01-01'
GROUP BY 1 ORDER BY 1;
EXPLAIN (COSTS OFF)
SELECT p.id, p.name, sum(oi.quantity) AS qty, sum(oi.quantity * oi.unit_price) AS sales
FROM orders o JOIN order_items oi ON oi.order_id = o.id JOIN products p ON p.id = oi.product_id
WHERE o.ordered_at >= '2025-12-25' AND o.ordered_at < '2026-01-01'
  AND o.status <> 'cancelled' AND p.category = '文具'
GROUP BY p.id, p.name ORDER BY sales DESC LIMIT 10;
-- 次に、ない状態（トランザクションの中で DROP して計画を見てから取り消す。Q5 → Q4）
BEGIN;
DROP INDEX orders_ordered_at_idx;
EXPLAIN (COSTS OFF)
SELECT date_trunc('day', o.ordered_at) AS day, count(DISTINCT o.customer_id) AS buyers,
       sum(oi.quantity * oi.unit_price) AS sales
FROM orders o JOIN order_items oi ON oi.order_id = o.id
WHERE o.status <> 'cancelled' AND o.ordered_at >= '2025-10-03' AND o.ordered_at < '2026-01-01'
GROUP BY 1 ORDER BY 1;
EXPLAIN (COSTS OFF)
SELECT p.id, p.name, sum(oi.quantity) AS qty, sum(oi.quantity * oi.unit_price) AS sales
FROM orders o JOIN order_items oi ON oi.order_id = o.id JOIN products p ON p.id = oi.product_id
WHERE o.ordered_at >= '2025-12-25' AND o.ordered_at < '2026-01-01'
  AND o.status <> 'cancelled' AND p.category = '文具'
GROUP BY p.id, p.name ORDER BY sales DESC LIMIT 10;
ROLLBACK;

-- 片付け（10 の設計には入れない）
DROP INDEX orders_ordered_at_idx;

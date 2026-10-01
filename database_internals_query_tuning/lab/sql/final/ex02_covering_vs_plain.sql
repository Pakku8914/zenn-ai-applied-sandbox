-- Final-ex02 明細のインデックスをカバリング（INCLUDE）にするか：大きさと Q1・Q4 の時間で比べる
-- 10 の後に実行する。比較用に INCLUDE なしのインデックスを一時的に作り、どちらか一方をサブトランザクションで DROP して
-- 交互に 5 回ずつ測る。最後に比較用のインデックスを消す
CREATE INDEX order_items_order_id_plain_idx ON order_items (order_id);
SELECT indexrelname AS index_name, pg_size_pretty(pg_relation_size(indexrelid)) AS size
FROM pg_stat_user_indexes WHERE relname = 'order_items' ORDER BY indexrelname;

CREATE OR REPLACE FUNCTION pg_temp.final_exec_ms(q text) RETURNS numeric
LANGUAGE plpgsql AS $$
DECLARE j json;
BEGIN
  EXECUTE 'EXPLAIN (ANALYZE, TIMING OFF, FORMAT JSON) ' || q INTO j;
  RETURN round((j -> 0 ->> 'Execution Time')::numeric, 3);
END $$;

-- 指定したインデックスがない状態で 1 回実行する（DROP INDEX はサブトランザクションごと取り消す）
CREATE OR REPLACE FUNCTION pg_temp.final_exec_ms_without(idx text, q text) RETURNS numeric
LANGUAGE plpgsql AS $$
DECLARE ms numeric;
BEGIN
  BEGIN
    EXECUTE format('DROP INDEX %I', idx);
    ms := pg_temp.final_exec_ms(q);
    RAISE EXCEPTION 'undo';
  EXCEPTION WHEN raise_exception THEN
    NULL;
  END;
  RETURN ms;
END $$;

DROP TABLE IF EXISTS pg_temp.final_ex02;
CREATE TEMP TABLE final_ex02 (query text, variant text, round int, ms numeric);
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
BEGIN
  PERFORM pg_temp.final_exec_ms_without('order_items_order_id_plain_idx', q4),
          pg_temp.final_exec_ms_without('order_items_order_id_idx', q4);
  FOR r IN 1..5 LOOP
    INSERT INTO final_ex02 VALUES ('Q1', 'INCLUDE あり', r, pg_temp.final_exec_ms_without('order_items_order_id_plain_idx', q1));
    INSERT INTO final_ex02 VALUES ('Q1', 'INCLUDE なし', r, pg_temp.final_exec_ms_without('order_items_order_id_idx', q1));
    INSERT INTO final_ex02 VALUES ('Q4', 'INCLUDE あり', r, pg_temp.final_exec_ms_without('order_items_order_id_plain_idx', q4));
    INSERT INTO final_ex02 VALUES ('Q4', 'INCLUDE なし', r, pg_temp.final_exec_ms_without('order_items_order_id_idx', q4));
  END LOOP;
END $$;
SELECT query, variant, percentile_cont(0.5) WITHIN GROUP (ORDER BY ms) AS median_ms
FROM final_ex02 GROUP BY query, variant ORDER BY query, variant;

-- INCLUDE なしのときの Q4 の計画（カバリングを DROP して見てから取り消す）
BEGIN;
DROP INDEX order_items_order_id_idx;
EXPLAIN (COSTS OFF)
SELECT p.id, p.name, sum(oi.quantity) AS qty, sum(oi.quantity * oi.unit_price) AS sales
FROM orders o JOIN order_items oi ON oi.order_id = o.id JOIN products p ON p.id = oi.product_id
WHERE o.ordered_at >= '2025-12-25' AND o.ordered_at < '2026-01-01'
  AND o.status <> 'cancelled' AND p.category = '文具'
GROUP BY p.id, p.name ORDER BY sales DESC LIMIT 10;
ROLLBACK;

-- 片付け
DROP INDEX order_items_order_id_plain_idx;

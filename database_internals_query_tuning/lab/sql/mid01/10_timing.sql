-- Mid01-10 3 本のクエリの改善前後を「交互に 5 回ずつ」測り、中央値と倍率を表にする（演習の成果物の見本）
-- 01〜09 を実行した後の状態で実行する（インデックス 3 本と mid01_import がある状態）
-- 時間は EXPLAIN (ANALYZE, TIMING OFF) の Execution Time。環境によって変わるので、倍率で比べる

-- 1 回実行して Execution Time（ミリ秒）を返す道具。pg_temp に作るので接続を切ると消える
CREATE OR REPLACE FUNCTION pg_temp.mid01_exec_ms(q text) RETURNS numeric
LANGUAGE plpgsql AS $$
DECLARE j json;
BEGIN
  EXECUTE 'EXPLAIN (ANALYZE, TIMING OFF, FORMAT JSON) ' || q INTO j;
  RETURN round((j -> 0 ->> 'Execution Time')::numeric, 3);
END $$;

-- 遅いクエリ B の「改善前」の状態（統計が昨夜のまま）を作り直す道具。05 と同じ手順
CREATE OR REPLACE FUNCTION pg_temp.mid01_stale_import() RETURNS void
LANGUAGE plpgsql AS $$
BEGIN
  TRUNCATE mid01_import;
  INSERT INTO mid01_import
  SELECT o.ordered_at::date, oi.order_id,
         row_number() OVER (PARTITION BY oi.order_id ORDER BY oi.id),
         oi.product_id, oi.quantity, oi.unit_price
  FROM order_items oi JOIN orders o ON o.id = oi.order_id
  WHERE o.ordered_at >= '2025-12-30' AND o.ordered_at < '2025-12-31';
  ANALYZE mid01_import;
  TRUNCATE mid01_import;
  INSERT INTO mid01_import
  SELECT o.ordered_at::date, oi.order_id,
         row_number() OVER (PARTITION BY oi.order_id ORDER BY oi.id),
         oi.product_id, oi.quantity, oi.unit_price
  FROM order_items oi JOIN orders o ON o.id = oi.order_id
  WHERE o.ordered_at >= '2025-12-31' AND o.ordered_at < '2026-01-01';
  INSERT INTO mid01_import
  SELECT batch_date, order_id, line_no + 10, product_id, quantity, unit_price
  FROM mid01_import
  WHERE line_no = 1
    AND order_id IN (SELECT DISTINCT order_id FROM mid01_import ORDER BY order_id LIMIT 3);
END $$;

DROP TABLE IF EXISTS pg_temp.mid01_timing;
CREATE TEMP TABLE mid01_timing (query text, variant text, round int, ms numeric);

DO $$
DECLARE
  a_before text := $q$SELECT o.id, o.ordered_at, o.status FROM customers c JOIN orders o ON o.customer_id = c.id
                      WHERE lower(c.email) = lower('User12345@Example.com') ORDER BY o.ordered_at DESC$q$;
  a_after  text := $q$SELECT o.id, o.ordered_at, o.status FROM customers c JOIN orders o ON o.customer_id = c.id
                      WHERE c.email = lower('User12345@Example.com') ORDER BY o.ordered_at DESC$q$;
  b_query  text := $q$SELECT count(*) AS dup_lines FROM mid01_import a JOIN mid01_import b
                      ON b.order_id = a.order_id AND b.product_id = a.product_id AND b.line_no > a.line_no
                      WHERE a.batch_date = DATE '2025-12-31' AND b.batch_date = DATE '2025-12-31'$q$;
  c_before text := $q$SELECT id, customer_id, ordered_at FROM (SELECT id, customer_id, ordered_at,
                      row_number() OVER (ORDER BY ordered_at DESC) AS rn FROM orders WHERE status = 'pending') t
                      WHERE rn <= 20 ORDER BY rn$q$;
  c_after  text := $q$SELECT id, customer_id, ordered_at FROM orders WHERE status = 'pending'
                      ORDER BY ordered_at DESC LIMIT 20$q$;
BEGIN
  -- 空回し（キャッシュを温める。記録しない）
  PERFORM pg_temp.mid01_exec_ms(a_before), pg_temp.mid01_exec_ms(a_after),
          pg_temp.mid01_exec_ms(c_before), pg_temp.mid01_exec_ms(c_after);
  FOR r IN 1..5 LOOP
    INSERT INTO mid01_timing VALUES ('A', '改善前', r, pg_temp.mid01_exec_ms(a_before));
    INSERT INTO mid01_timing VALUES ('A', '改善後', r, pg_temp.mid01_exec_ms(a_after));
    -- B は「統計が昨夜のまま」と「ANALYZE 後」を交互に作り直して測る
    PERFORM pg_temp.mid01_stale_import();
    INSERT INTO mid01_timing VALUES ('B', '改善前', r, pg_temp.mid01_exec_ms(b_query));
    ANALYZE mid01_import;
    INSERT INTO mid01_timing VALUES ('B', '改善後', r, pg_temp.mid01_exec_ms(b_query));
    INSERT INTO mid01_timing VALUES ('C', '改善前', r, pg_temp.mid01_exec_ms(c_before));
    INSERT INTO mid01_timing VALUES ('C', '改善後', r, pg_temp.mid01_exec_ms(c_after));
  END LOOP;
END $$;

-- 中央値と倍率
SELECT query,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY ms) FILTER (WHERE variant = '改善前') AS before_ms,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY ms) FILTER (WHERE variant = '改善後') AS after_ms,
       round((percentile_cont(0.5) WITHIN GROUP (ORDER BY ms) FILTER (WHERE variant = '改善前')
            / percentile_cont(0.5) WITHIN GROUP (ORDER BY ms) FILTER (WHERE variant = '改善後'))::numeric, 0) AS ratio
FROM mid01_timing
GROUP BY query
ORDER BY query;

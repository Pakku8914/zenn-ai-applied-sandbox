-- 練習（模範解答・発展）: 境界探しの二分探索を PL/pgSQL で自動化する。
-- EXPLAIN (FORMAT JSON) の結果を json として受け取り、最上位ノードの種類を比べる。
-- 前提: 01_create_indexes.sql 実行済み
DO $$
DECLARE
  lo bigint := 500000;   -- Index Scan になる値
  hi bigint := 700000;   -- Seq Scan になる値
  mid bigint;
  plan json;
  node text;
  step int := 0;
BEGIN
  WHILE hi - lo > 1 LOOP
    mid := (lo + hi) / 2;
    EXECUTE format('EXPLAIN (FORMAT JSON) SELECT * FROM orders WHERE id BETWEEN 1 AND %s', mid) INTO plan;
    node := plan -> 0 -> 'Plan' ->> 'Node Type';
    step := step + 1;
    RAISE NOTICE 'step % : n = % -> % (rows=%)', step, mid, node, plan -> 0 -> 'Plan' ->> 'Plan Rows';
    IF node = 'Index Scan' THEN lo := mid; ELSE hi := mid; END IF;
  END LOOP;
  RAISE NOTICE '境界: % までは Index Scan、% からは Seq Scan', lo, hi;
END $$;

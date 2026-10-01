-- S07-07 結合するテーブルが増えると、結合順序の探索（計画作成）そのものが重くなる
-- 100 行だけの作業用テーブル s07_t1 … s07_t14 を id で数珠つなぎに結合し、Planning Time と計画に使ったメモリを測る
-- 注意：geqo = off のまま 11 個以上を結合すると、計画だけで数百 MB〜数 GB のメモリを使う
--       （この環境では 13 個でサーバープロセスが OOM Killer に止められ、全接続が切断された）。このファイルの範囲を超えて試さないこと

SELECT format('DROP TABLE IF EXISTS s07_t%s', i) FROM generate_series(1, 14) AS i \gexec
SELECT format('CREATE TABLE s07_t%s AS SELECT g AS id FROM generate_series(1, 100) AS g', i) FROM generate_series(1, 14) AS i \gexec
SELECT format('ANALYZE s07_t%s', i) FROM generate_series(1, 14) AS i \gexec

-- n 個のテーブルを結合するクエリを組み立て、EXPLAIN（実行はしない）を 5 回行って Planning Time の中央値を返す一時関数。
-- pg_temp に作るのでセッションを閉じると消える
-- join_syntax = false: FROM s07_t1, s07_t2, ... WHERE s07_t1.id = s07_t2.id AND ...（カンマ区切り）
-- join_syntax = true : FROM s07_t1 JOIN s07_t2 ON ... JOIN s07_t3 ON ...（明示的な JOIN）
CREATE FUNCTION pg_temp.s07_plan(n int, join_syntax boolean DEFAULT false)
RETURNS TABLE (tables int, planning_ms numeric, planner_memory_kb bigint)
LANGUAGE plpgsql AS $$
DECLARE
  q  text;
  j  json;
  ts numeric[] := '{}';
  mem bigint;
BEGIN
  IF join_syntax THEN
    q := 'SELECT count(*) FROM s07_t1'
      || (SELECT string_agg(format(' JOIN s07_t%s ON s07_t%s.id = s07_t%s.id', i, i, i - 1), '' ORDER BY i)
          FROM generate_series(2, n) AS i);
  ELSE
    q := 'SELECT count(*) FROM '
      || (SELECT string_agg(format('s07_t%s', i), ', ' ORDER BY i) FROM generate_series(1, n) AS i)
      || ' WHERE '
      || (SELECT string_agg(format('s07_t%s.id = s07_t%s.id', i, i + 1), ' AND ' ORDER BY i)
          FROM generate_series(1, n - 1) AS i);
  END IF;
  FOR k IN 1..5 LOOP
    EXECUTE 'EXPLAIN (FORMAT JSON, SUMMARY, MEMORY, COSTS OFF) ' || q INTO j;
    ts  := ts || (j -> 0 ->> 'Planning Time')::numeric;
    mem := (j -> 0 -> 'Planning' ->> 'Memory Used')::bigint;
  END LOOP;
  RETURN QUERY
    SELECT n,
           (SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY x) FROM unnest(ts) AS x)::numeric(10, 3),
           mem;
END $$;

-- (1) 既定の設定（geqo = on, geqo_threshold = 12）。10 個までは全探索、12 個からは遺伝的アルゴリズム（GEQO）に切り替わる
SHOW geqo_threshold;
SELECT r.* FROM unnest(ARRAY[2, 4, 6, 8, 10, 12, 14]) AS n, pg_temp.s07_plan(n) AS r;

-- (2) 明示的な JOIN で書くと、join_collapse_limit（既定 8）を超えた分は書いた順のまま固定され、探索が打ち切られる
SHOW join_collapse_limit;
SELECT r.* FROM unnest(ARRAY[8, 10, 12, 14]) AS n, pg_temp.s07_plan(n, true) AS r;

-- (3) 4 テーブルでの計画の形（計画時間とメモリの表示の例）
EXPLAIN (SUMMARY, MEMORY, COSTS OFF)
SELECT count(*) FROM s07_t1, s07_t2, s07_t3, s07_t4
WHERE s07_t1.id = s07_t2.id AND s07_t2.id = s07_t3.id AND s07_t3.id = s07_t4.id;

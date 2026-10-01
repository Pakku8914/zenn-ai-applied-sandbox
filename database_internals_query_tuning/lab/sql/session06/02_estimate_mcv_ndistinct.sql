-- 等値条件の見積もりを、pg_stats の値から手計算で再現する。
-- 見積もり行数 = テーブルの行数（pg_class.reltuples）× 選択率

-- (1) MCV にある値: 選択率 = その値の頻度
SELECT c.reltuples AS 行数,
       s.most_common_freqs[array_position(s.most_common_vals::text::text[], 'pending')] AS pending_の頻度,
       round(c.reltuples * s.most_common_freqs[array_position(s.most_common_vals::text::text[], 'pending')]) AS 手計算の見積もり
FROM pg_stats s JOIN pg_class c ON c.relname = s.tablename
WHERE s.tablename = 'orders' AND s.attname = 'status';

EXPLAIN SELECT * FROM orders WHERE status = 'pending';

-- (2) 否定条件: 選択率 = 1 − その値の頻度
EXPLAIN SELECT * FROM orders WHERE status <> 'completed';

-- (3) MCV にない値: MCV の頻度の合計が 1 なので「残りは 0」と見なされ、下限の 1 行になる
EXPLAIN SELECT * FROM orders WHERE status = 'refunded';

-- (4) MCV を持たない列: 選択率 = 1 / n_distinct
SELECT c.reltuples AS 行数, s.n_distinct, round(c.reltuples / s.n_distinct) AS 手計算の見積もり
FROM pg_stats s JOIN pg_class c ON c.relname = s.tablename
WHERE s.tablename = 'orders' AND s.attname = 'customer_id';

EXPLAIN SELECT * FROM orders WHERE customer_id = 777;

-- (5) 実測と比べる
EXPLAIN (ANALYZE) SELECT * FROM orders WHERE status = 'pending';
EXPLAIN (ANALYZE) SELECT * FROM orders WHERE customer_id = 777;

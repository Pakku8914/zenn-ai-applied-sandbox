-- S16 演習：プルーニングが効かない条件を、効く形に書き換える
-- 01_range_partition.sql の後に実行する（s16_orders が必要）

-- (1) 書き換え前：パーティションキーに関数をかけているので12個すべてを読む
EXPLAIN (ANALYZE, COSTS OFF)
SELECT count(*) FROM s16_orders
WHERE date_trunc('month', ordered_at) = '2025-06-01';

-- (2) 書き換え後：パーティションキーそのものの範囲条件（半開区間）にする
EXPLAIN (ANALYZE, COSTS OFF)
SELECT count(*) FROM s16_orders
WHERE ordered_at >= '2025-06-01' AND ordered_at < '2025-07-01';

-- (3) 落とし穴：date 型の値と比べると、timestamptz への変換がタイムゾーンに依存するため、
--     計画を作る時点では外せない。実行を始めるときに外される（Subplans Removed）
EXPLAIN (ANALYZE, COSTS OFF)
SELECT count(*) FROM s16_orders
WHERE ordered_at >= DATE '2025-06-01' AND ordered_at < DATE '2025-07-01';

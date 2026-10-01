-- S16-04 範囲外の行と DEFAULT パーティション
-- 01_range_partition.sql の後に実行する

-- (1) どのパーティションにも入らない行（2026年1月）はエラーになる
INSERT INTO s16_orders VALUES (1000001, 1, '2026-01-15 12:00:00+00', 'pending');

-- (2) DEFAULT パーティションを作ると、どこにも当てはまらない行を受け止める
CREATE TABLE s16_orders_default PARTITION OF s16_orders DEFAULT;
INSERT INTO s16_orders VALUES (1000001, 1, '2026-01-15 12:00:00+00', 'pending');
SELECT tableoid::regclass AS partition, id, ordered_at FROM s16_orders WHERE id = 1000001;

-- (3) 12月の後半から1月にまたがる検索は、12月と DEFAULT の2つを読む
EXPLAIN (ANALYZE, COSTS OFF)
SELECT count(*) FROM s16_orders
WHERE ordered_at >= '2025-12-15' AND ordered_at < '2026-01-15';

-- (4) 6月だけの検索では DEFAULT は外れる（境界が6月のパーティションで閉じているため）
EXPLAIN (ANALYZE, COSTS OFF)
SELECT count(*) FROM s16_orders
WHERE ordered_at >= '2025-06-01' AND ordered_at < '2025-07-01';

-- (5) DEFAULT に 2026年1月の行があると、あとから 2026年1月のパーティションを作れない
CREATE TABLE s16_orders_2026_01 PARTITION OF s16_orders FOR VALUES FROM ('2026-01-01') TO ('2026-02-01');

-- (6) DEFAULT があると DETACH PARTITION ... CONCURRENTLY は使えない
ALTER TABLE s16_orders DETACH PARTITION s16_orders_2025_01 CONCURRENTLY;

-- 後片付け：05 のために DEFAULT パーティションを外して消す
DROP TABLE s16_orders_default;

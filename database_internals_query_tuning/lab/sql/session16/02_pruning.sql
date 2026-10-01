-- S16-02 パーティションプルーニング：効く書き方と効かない書き方
-- 01_range_partition.sql の後に実行する

-- (1) 比較用：パーティションなしの orders（インデックスは主キーだけ）で6月の件数を数える
EXPLAIN (ANALYZE, BUFFERS)
SELECT count(*) FROM orders
WHERE ordered_at >= '2025-06-01' AND ordered_at < '2025-07-01';

-- (2) パーティションキーの範囲条件：6月のパーティションだけを読む（計画に他の月が出てこない）
EXPLAIN (ANALYZE, BUFFERS)
SELECT count(*) FROM s16_orders
WHERE ordered_at >= '2025-06-01' AND ordered_at < '2025-07-01';

-- (3) パーティションキーに関数をかける：12個すべてを読む
EXPLAIN (ANALYZE, BUFFERS)
SELECT count(*) FROM s16_orders
WHERE date_trunc('month', ordered_at) = '2025-06-01';

-- (4) ::date に変換する（timestamptz → date はタイムゾーンで結果が変わるので、境界と突き合わせられない）
EXPLAIN (ANALYZE, BUFFERS)
SELECT count(*) FROM s16_orders
WHERE ordered_at::date BETWEEN '2025-06-01' AND '2025-06-30';

-- (5) パーティションキー以外の条件だけ：12個すべてを読む
EXPLAIN (ANALYZE, BUFFERS)
SELECT count(*) FROM s16_orders
WHERE status = 'cancelled';

-- (6) 結果はどれも同じ件数になる（(5) を除く）
SELECT
  (SELECT count(*) FROM s16_orders WHERE ordered_at >= '2025-06-01' AND ordered_at < '2025-07-01') AS by_range,
  (SELECT count(*) FROM s16_orders WHERE date_trunc('month', ordered_at) = '2025-06-01') AS by_date_trunc,
  (SELECT count(*) FROM s16_orders WHERE ordered_at::date BETWEEN '2025-06-01' AND '2025-06-30') AS by_date_cast;

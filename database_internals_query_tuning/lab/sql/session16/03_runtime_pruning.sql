-- S16-03 実行時のプルーニング：値が実行するまで分からないとき
-- 01_range_partition.sql の後に実行する

-- (1) パラメータ付きのプリペアド文。汎用プラン（値を決めずに作る計画）を強制すると、
--     計画には12個すべてが載り、実行を始めるときに11個が外される（Subplans Removed）
PREPARE s16_range(timestamptz, timestamptz) AS
SELECT count(*) FROM s16_orders
WHERE ordered_at >= $1 AND ordered_at < $2;

SET plan_cache_mode = force_generic_plan;
EXPLAIN (ANALYZE, BUFFERS) EXECUTE s16_range('2025-06-01', '2025-07-01');

-- (2) 既定（auto）では最初の5回は値を埋め込んだ専用プランを作るので、計画を作る時点で6月だけになる
SET plan_cache_mode = auto;
EXPLAIN (ANALYZE, BUFFERS) EXECUTE s16_range('2025-06-01', '2025-07-01');
DEALLOCATE s16_range;
RESET plan_cache_mode;

-- (3) timestamptz + interval はタイムゾーンで結果が変わる（安定関数）ので、計画を作る時点では計算しない。
--     下限の定数で1〜5月は計画から外れ、上限の式は実行を始めるときに評価されて7〜12月が外れる
EXPLAIN (ANALYZE, BUFFERS)
SELECT count(*) FROM s16_orders
WHERE ordered_at >= '2025-06-01' AND ordered_at < '2025-06-01'::timestamptz + interval '1 month';

-- Index Only Scan が成立する条件（Visibility Map）を確かめる。
-- 4 テーブルを直接いじると物理的な痕跡（ページ数の増加など）が残るため、作業用コピー s05_orders で行う。
-- 自動 VACUUM が途中で走ると観察にならないので、このテーブルだけ autovacuum を止めておく。

CREATE EXTENSION IF NOT EXISTS pg_visibility;   -- Visibility Map を覗く拡張（PostgreSQL 同梱）

CREATE TABLE s05_orders WITH (autovacuum_enabled = false) AS SELECT * FROM orders;
CREATE INDEX s05_orders_ordered_at_idx ON s05_orders (ordered_at);
VACUUM (ANALYZE) s05_orders;

-- (1) VACUUM 直後: 全ページが all-visible
SELECT * FROM pg_visibility_map_summary('s05_orders');

EXPLAIN (ANALYZE, BUFFERS)
SELECT count(*) FROM s05_orders
WHERE ordered_at >= '2025-06-01' AND ordered_at < '2025-06-02';

-- (2) 更新して取り消す。行の中身は元どおりだが、触ったページの all-visible ビットは落ちる
BEGIN;
UPDATE s05_orders SET status = status
WHERE ordered_at >= '2025-06-01' AND ordered_at < '2025-06-02';
ROLLBACK;

SELECT * FROM pg_visibility_map_summary('s05_orders');

-- 同じ Index Only Scan を 2 回続けて実行する
EXPLAIN (ANALYZE, BUFFERS)
SELECT count(*) FROM s05_orders
WHERE ordered_at >= '2025-06-01' AND ordered_at < '2025-06-02';

EXPLAIN (ANALYZE, BUFFERS)
SELECT count(*) FROM s05_orders
WHERE ordered_at >= '2025-06-01' AND ordered_at < '2025-06-02';

-- (3) VACUUM で Visibility Map を立て直す
VACUUM (VERBOSE) s05_orders;

SELECT * FROM pg_visibility_map_summary('s05_orders');

EXPLAIN (ANALYZE, BUFFERS)
SELECT count(*) FROM s05_orders
WHERE ordered_at >= '2025-06-01' AND ordered_at < '2025-06-02';

-- (4) 不要行が少ないと VACUUM はインデックスの掃除を省略する（index scan bypassed）。
--     INDEX_CLEANUP ON で掃除を強制すると Heap Fetches が 0 に戻る
VACUUM (INDEX_CLEANUP ON) s05_orders;

SELECT * FROM pg_visibility_map_summary('s05_orders');

EXPLAIN (ANALYZE, BUFFERS)
SELECT count(*) FROM s05_orders
WHERE ordered_at >= '2025-06-01' AND ordered_at < '2025-06-02';

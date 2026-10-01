-- S09-04 部分インデックス：一部の行だけを索引にして小さく保つ
-- pending は約 13.7%、cancelled は約 4.3%。出発点から実行する

-- (1) 全行の ordered_at インデックスと、pending・cancelled だけの部分インデックスを作って大きさを比べる
CREATE INDEX orders_ordered_at_idx ON orders (ordered_at);
CREATE INDEX orders_pending_ordered_at_idx ON orders (ordered_at) WHERE status = 'pending';
CREATE INDEX orders_cancelled_ordered_at_idx ON orders (ordered_at) WHERE status = 'cancelled';
SELECT indexrelid::regclass AS index_name,
       pg_size_pretty(pg_relation_size(indexrelid)) AS size,
       pg_relation_size(indexrelid) / 8192 AS pages,
       pg_get_expr(indpred, indrelid) AS predicate
FROM pg_index
WHERE indrelid = 'orders'::regclass AND indexrelid <> 'orders_pkey'::regclass
ORDER BY pg_relation_size(indexrelid);

-- (2) Mid01 の遅いクエリ C（書き換え後）：部分インデックスが選ばれ、Filter が消える（条件がインデックスの定義に含まれるため）
EXPLAIN (ANALYZE, BUFFERS)
SELECT id, customer_id, ordered_at
FROM orders
WHERE status = 'pending'
ORDER BY ordered_at DESC
LIMIT 20;

-- (3) 6 月の cancelled の件数：部分インデックスだけで数え終わる（Index Only Scan）
EXPLAIN (ANALYZE, BUFFERS)
SELECT count(*)
FROM orders
WHERE status = 'cancelled'
  AND ordered_at >= '2025-06-01' AND ordered_at < '2025-07-01';

-- (4) 条件が一致しないと使われない
-- (4a) completed は部分インデックスの対象外
EXPLAIN
SELECT id, customer_id, ordered_at
FROM orders
WHERE status = 'completed'
ORDER BY ordered_at DESC
LIMIT 20;

-- (4b) IN で 2 つの値を並べると、どちらの部分インデックスの条件にも「含まれる」と言えない
EXPLAIN
SELECT count(*)
FROM orders
WHERE status IN ('pending', 'cancelled')
  AND ordered_at >= '2025-06-01' AND ordered_at < '2025-06-02';

-- (4c) 値をパラメータで渡す汎用プラン（generic plan）では、値が pending かどうかを計画時に判断できない
PREPARE s09_pending_list(text) AS
SELECT id, customer_id, ordered_at
FROM orders
WHERE status = $1
ORDER BY ordered_at DESC
LIMIT 20;
SET plan_cache_mode = force_generic_plan;
EXPLAIN EXECUTE s09_pending_list('pending');
SET plan_cache_mode = force_custom_plan;
EXPLAIN EXECUTE s09_pending_list('pending');
RESET plan_cache_mode;
DEALLOCATE s09_pending_list;

-- 後片付け
DROP INDEX orders_ordered_at_idx, orders_pending_ordered_at_idx, orders_cancelled_ordered_at_idx;

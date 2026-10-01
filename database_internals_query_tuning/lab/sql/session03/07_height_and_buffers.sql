-- セッション3-7: 1 件を探すのに読むページ数 = 木の高さ（＋ヒープ 1 ページ）
-- 02_create_index.sql を実行した後に実行する。同じセッションで 2 回実行し、2 回目の Buffers を読む
SELECT id, ordered_at FROM orders WHERE id = 204551;

EXPLAIN (ANALYZE, BUFFERS) SELECT * FROM orders WHERE ordered_at = '2025-06-01 10:00:11+00';
EXPLAIN (ANALYZE, BUFFERS) SELECT * FROM orders WHERE ordered_at = '2025-06-01 10:00:11+00';

-- 存在しないキーを探しても、リーフまでは降りる（ヒープは読まない）
EXPLAIN (ANALYZE, BUFFERS) SELECT * FROM orders WHERE ordered_at = '2025-06-01 10:00:12+00';

-- 木の高さ
SELECT level + 1 AS height FROM bt_metap('orders_ordered_at_idx');

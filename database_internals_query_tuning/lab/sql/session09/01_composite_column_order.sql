-- S09-01 複合インデックスの列順：等値条件の列を先に、範囲条件の列を後に
-- 出発点（tools/reset.sh 直後）から実行する。題材は「期間内の未処理（pending）の注文」

-- (1) 単一列のインデックス（ordered_at）だけがある状態
CREATE INDEX orders_ordered_at_idx ON orders (ordered_at);

-- (1a) 1 週間分の pending の一覧：status はヒープを読んでから Filter で捨てる
EXPLAIN (ANALYZE, BUFFERS)
SELECT id, customer_id, ordered_at
FROM orders
WHERE status = 'pending'
  AND ordered_at >= '2025-06-01' AND ordered_at < '2025-06-08';

-- (1b) 6 月の pending の件数：同じく Filter。インデックスで 8 万行を拾ってからヒープで 7 万行を捨てる
EXPLAIN (ANALYZE, BUFFERS)
SELECT count(*)
FROM orders
WHERE status = 'pending'
  AND ordered_at >= '2025-06-01' AND ordered_at < '2025-07-01';

-- (2) 等値の列（status）を先、範囲の列（ordered_at）を後にした複合インデックス
CREATE INDEX orders_status_ordered_at_idx ON orders (status, ordered_at);

EXPLAIN (ANALYZE, BUFFERS)
SELECT id, customer_id, ordered_at
FROM orders
WHERE status = 'pending'
  AND ordered_at >= '2025-06-01' AND ordered_at < '2025-06-08';

EXPLAIN (ANALYZE, BUFFERS)
SELECT count(*)
FROM orders
WHERE status = 'pending'
  AND ordered_at >= '2025-06-01' AND ordered_at < '2025-07-01';

-- (3) 逆の列順（範囲の列を先）。(2) を消してから作る
DROP INDEX orders_status_ordered_at_idx;
CREATE INDEX orders_ordered_at_status_idx ON orders (ordered_at, status);

EXPLAIN (ANALYZE, BUFFERS)
SELECT count(*)
FROM orders
WHERE status = 'pending'
  AND ordered_at >= '2025-06-01' AND ordered_at < '2025-07-01';

-- (4) 3 つのインデックスの大きさ（(2) を作り直して並べる）
CREATE INDEX orders_status_ordered_at_idx ON orders (status, ordered_at);
SELECT indexrelid::regclass AS index_name,
       pg_size_pretty(pg_relation_size(indexrelid)) AS size,
       pg_relation_size(indexrelid) / 8192 AS pages
FROM pg_index
WHERE indrelid = 'orders'::regclass AND indexrelid <> 'orders_pkey'::regclass
ORDER BY index_name;

-- 後片付け（次のファイルは自分で必要なインデックスを作る）
DROP INDEX orders_ordered_at_idx, orders_status_ordered_at_idx, orders_ordered_at_status_idx;

-- S15-01 PostgreSQL（ヒープ＋インデックス）：主キー順の範囲読みと、セカンダリインデックス経由の読み
-- 先に出発点へ戻しておく: docker compose exec lab bash tools/reset.sh
-- 02_mysql_primary_and_secondary.sql と同じクエリを MySQL で実行して見比べる

-- (1) ordered_at のインデックスを作る（S03 と同じもの。リーフは「キー + 行の位置（ctid）」を持つ）
CREATE INDEX orders_ordered_at_idx ON orders (ordered_at);

-- (2) 主キー順の範囲読み（10万行）
EXPLAIN (ANALYZE, BUFFERS)
SELECT * FROM orders WHERE id BETWEEN 200001 AND 300000;

-- (3) 主キー順に並んでいるのは「id の順に INSERT したから」。correlation がそれを表す
SELECT attname, correlation FROM pg_stats
WHERE tablename = 'orders' AND attname IN ('id', 'ordered_at')
ORDER BY attname;

-- (4) 1週間分の id と ordered_at だけを取る。(ordered_at) のインデックスは id を持たないので、ヒープを読む
EXPLAIN (ANALYZE, BUFFERS)
SELECT id, ordered_at FROM orders
WHERE ordered_at >= '2025-06-01' AND ordered_at < '2025-06-08';

-- (5) 全列を取る場合も同じ Bitmap Heap Scan（2,878 ページに散らばった行を物理順に読む）
EXPLAIN (ANALYZE, BUFFERS)
SELECT * FROM orders
WHERE ordered_at >= '2025-06-01' AND ordered_at < '2025-06-08';

-- (6) id をインデックスに含めると Index Only Scan になる（InnoDB のセカンダリインデックスは最初からこの形）
CREATE INDEX orders_ordered_at_id_idx ON orders (ordered_at) INCLUDE (id);
EXPLAIN (ANALYZE, BUFFERS)
SELECT id, ordered_at FROM orders
WHERE ordered_at >= '2025-06-01' AND ordered_at < '2025-06-08';

-- (7) 2つのインデックスの大きさ（ページ数）
SELECT c.relname, pg_relation_size(c.oid) / 8192 AS pages
FROM pg_class c
WHERE c.relname IN ('orders_pkey', 'orders_ordered_at_idx', 'orders_ordered_at_id_idx')
ORDER BY c.relname;

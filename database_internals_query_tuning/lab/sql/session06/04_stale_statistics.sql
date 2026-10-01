-- 統計が古いと何が起きるか。作業用コピー s06_orders で行う。
-- autovacuum_naptime = 10s のサンドボックスでは、放っておくと自動 ANALYZE が走って実験にならないので、
-- このテーブルだけ autovacuum を止める（止めないとどうなるかは 05_autoanalyze.sql）。
CREATE TABLE s06_orders WITH (autovacuum_enabled = false) AS SELECT * FROM orders;
CREATE INDEX s06_orders_status_idx ON s06_orders (status);
ANALYZE s06_orders;

-- (1) まだ 'returned' という状態の注文はない
EXPLAIN (ANALYZE, BUFFERS)
SELECT o.id, c.region FROM s06_orders o JOIN customers c ON c.id = o.customer_id
WHERE o.status = 'returned';

-- (2) 返品処理で 'returned' の行が 25 万件一気に増えた（統計はまだ古いまま）
INSERT INTO s06_orders (id, customer_id, ordered_at, status)
SELECT id + 1000000, customer_id, ordered_at + interval '1 year', 'returned'
FROM orders WHERE id % 4 = 0;

-- 統計は INSERT 前のまま（'returned' は MCV にない）
SELECT most_common_vals, most_common_freqs FROM pg_stats
WHERE tablename = 's06_orders' AND attname = 'status';

EXPLAIN (ANALYZE, BUFFERS)
SELECT o.id, c.region FROM s06_orders o JOIN customers c ON c.id = o.customer_id
WHERE o.status = 'returned';

-- (3) ANALYZE で統計を取り直すと、見積もりもプランも変わる
ANALYZE s06_orders;

SELECT most_common_vals, most_common_freqs FROM pg_stats
WHERE tablename = 's06_orders' AND attname = 'status';

EXPLAIN (ANALYZE, BUFFERS)
SELECT o.id, c.region FROM s06_orders o JOIN customers c ON c.id = o.customer_id
WHERE o.status = 'returned';

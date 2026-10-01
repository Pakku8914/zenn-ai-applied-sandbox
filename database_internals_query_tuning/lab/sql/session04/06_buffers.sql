-- セッション4-6: BUFFERS の shared hit / read を読む
-- まだメモリ（共有バッファ）に載っていない新しいテーブルを作る
-- （CREATE TABLE ... AS と VACUUM は少しのバッファだけを使い回すので、ほとんどのページはメモリに残らない）
DROP TABLE IF EXISTS s04_orders;
CREATE TABLE s04_orders AS SELECT * FROM orders;
CREATE INDEX s04_orders_ordered_at_idx ON s04_orders (ordered_at);
VACUUM (ANALYZE) s04_orders;

-- 1 回目: read（共有バッファになかったので外から読んだ）が多い
EXPLAIN (ANALYZE, BUFFERS)
SELECT * FROM s04_orders
WHERE ordered_at >= '2025-06-01' AND ordered_at < '2025-06-02';

-- 2 回目: 同じページがもう共有バッファにあるので、すべて hit になる
EXPLAIN (ANALYZE, BUFFERS)
SELECT * FROM s04_orders
WHERE ordered_at >= '2025-06-01' AND ordered_at < '2025-06-02';

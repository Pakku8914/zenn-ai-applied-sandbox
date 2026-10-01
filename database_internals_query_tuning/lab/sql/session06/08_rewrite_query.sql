-- 統計が使えない書き方をしていると、どれだけ ANALYZE しても見積もりは直らない。
-- 列に関数を適用した条件は「既定の選択率 0.5%」で見積もられる。

-- (1) lower(status) = 'pending': 見積もり 5,000 行（100 万 × 0.005）、実際は 136,646 行
EXPLAIN (ANALYZE) SELECT count(*) FROM orders WHERE lower(status) = 'pending';

-- (2) 書き換え: status の値はもともと小文字なので lower() は要らない
EXPLAIN (ANALYZE) SELECT count(*) FROM orders WHERE status = 'pending';

-- (3) 書き換えられないとき: 式に統計を取らせる（PostgreSQL 14 以降の式の拡張統計）
CREATE STATISTICS s06_orders_lower_status ON (lower(status)) FROM orders;
ANALYZE orders;
EXPLAIN (ANALYZE) SELECT count(*) FROM orders WHERE lower(status) = 'pending';
DROP STATISTICS s06_orders_lower_status;
ANALYZE orders;

-- (4) 型変換も同じ: ordered_at::date = ... は 0.5%（5,000 行）と見積もられる
EXPLAIN SELECT * FROM orders WHERE ordered_at::date = '2025-06-01';
EXPLAIN SELECT * FROM orders WHERE ordered_at >= '2025-06-01' AND ordered_at < '2025-06-02';

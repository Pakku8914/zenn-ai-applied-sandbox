-- セッション4-9: 列に関数（型変換）を適用した条件と、範囲条件の比較
-- 「ordered_at::date = 日付」はインデックスのキー（ordered_at そのもの）と形が違うので使えない
EXPLAIN (ANALYZE, BUFFERS)
SELECT * FROM orders WHERE ordered_at::date = '2025-06-01';

-- 同じ行を範囲条件で書く
EXPLAIN (ANALYZE, BUFFERS)
SELECT * FROM orders
WHERE ordered_at >= '2025-06-01' AND ordered_at < '2025-06-02';

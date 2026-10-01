-- セッション4-4: 計画木を内側（字下げの深い行）から外側へ読む
-- 2025-06-01 の注文を status ごとに数えて、status の順に並べる
EXPLAIN (ANALYZE, BUFFERS)
SELECT status, count(*)
FROM orders
WHERE ordered_at >= '2025-06-01' AND ordered_at < '2025-06-02'
GROUP BY status
ORDER BY status;

-- 結果（計画木の一番外側の Sort が返す 3 行）
SELECT status, count(*)
FROM orders
WHERE ordered_at >= '2025-06-01' AND ordered_at < '2025-06-02'
GROUP BY status
ORDER BY status;

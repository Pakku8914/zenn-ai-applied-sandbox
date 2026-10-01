-- セッション3-1: インデックスがない状態の 1 日分の範囲検索（環境構築章で見た計画）
-- 最初に tools/reset.sh で出発点に戻しておく（主キーと外部キーだけの状態）
EXPLAIN (ANALYZE, BUFFERS)
SELECT * FROM orders
WHERE ordered_at >= '2025-06-01' AND ordered_at < '2025-06-02';

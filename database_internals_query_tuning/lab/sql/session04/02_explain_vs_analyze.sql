-- セッション4-2: EXPLAIN と EXPLAIN ANALYZE の違い
-- EXPLAIN だけ: クエリを実行しない。プランナの見積もり（cost と rows）だけが出る
EXPLAIN
SELECT * FROM orders
WHERE ordered_at >= '2025-06-01' AND ordered_at < '2025-06-02';

-- EXPLAIN ANALYZE: 実際に実行して、見積もりの横に実測（actual time・rows・loops）を並べる。
-- PostgreSQL 18 では ANALYZE を付けると BUFFERS（読んだページ数）も既定で表示される
EXPLAIN ANALYZE
SELECT * FROM orders
WHERE ordered_at >= '2025-06-01' AND ordered_at < '2025-06-02';

-- BUFFERS を消したいときは明示的に OFF にする（本書では基本的に付けたまま読む）
EXPLAIN (ANALYZE, BUFFERS OFF)
SELECT * FROM orders
WHERE ordered_at >= '2025-06-01' AND ordered_at < '2025-06-02';

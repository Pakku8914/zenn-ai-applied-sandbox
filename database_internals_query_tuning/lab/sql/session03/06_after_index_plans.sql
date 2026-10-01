-- セッション3-6: インデックスを作った後、実行計画はどう変わるか
-- 02_create_index.sql を実行した後に実行する

-- (1) 1 日分（約 2,740 行）: Index Scan ではなく Bitmap Heap Scan が選ばれる
EXPLAIN (ANALYZE, BUFFERS)
SELECT * FROM orders
WHERE ordered_at >= '2025-06-01' AND ordered_at < '2025-06-02';

-- 1 日分の 2,740 行は何ページに散らばっているか（ordered_at は id の並び＝物理順と無関係）
SELECT count(*) AS rows, count(DISTINCT (ctid::text::point)[0]) AS pages
FROM orders
WHERE ordered_at >= '2025-06-01' AND ordered_at < '2025-06-02';

-- プランナが見ている「キーの順序と物理順の相関」（1 に近いほど揃っている。0 付近は無関係）
SELECT attname, correlation FROM pg_stats
WHERE tablename = 'orders' AND attname IN ('id', 'ordered_at')
ORDER BY attname;

-- 比較のため Bitmap を禁止して、Index Scan を選ばせたときのコスト
SET enable_bitmapscan = off;
EXPLAIN (ANALYZE, BUFFERS)
SELECT * FROM orders
WHERE ordered_at >= '2025-06-01' AND ordered_at < '2025-06-02';
RESET enable_bitmapscan;

-- (2) 範囲を狭めると Index Scan が選ばれる（1 分間 = 3 行）
EXPLAIN (ANALYZE, BUFFERS)
SELECT * FROM orders
WHERE ordered_at >= '2025-06-01 10:00' AND ordered_at < '2025-06-01 10:01';

-- (3) 1 時間分（約 116 行）はまだ Bitmap Heap Scan
EXPLAIN (ANALYZE, BUFFERS)
SELECT * FROM orders
WHERE ordered_at >= '2025-06-01 10:00' AND ordered_at < '2025-06-01 11:00';

-- (4) リーフがキー順に並んでいるので、ORDER BY ... LIMIT はソートなしで先頭から読むだけ
EXPLAIN (ANALYZE, BUFFERS)
SELECT * FROM orders ORDER BY ordered_at LIMIT 10;

-- (5) 主キーで 1 行: Index Scan。2 回実行して 2 回目の Buffers を見る
--     （接続して最初の実行は余分なページを読むことがあるので、2 回目の Buffers で数える）
EXPLAIN (ANALYZE, BUFFERS) SELECT * FROM orders WHERE id = 123456;
EXPLAIN (ANALYZE, BUFFERS) SELECT * FROM orders WHERE id = 123457;

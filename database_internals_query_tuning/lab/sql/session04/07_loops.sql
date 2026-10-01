-- セッション4-7: loops（内側のノードが何回実行されたか）
-- 2025-06-01 10 時台の注文（116 件）と、その注文をした顧客の名前
-- 外側の 116 行それぞれについて、内側で customers を主キーで 1 回ずつ引く（Nested Loop）
EXPLAIN (ANALYZE, BUFFERS)
SELECT o.id, c.name
FROM orders o
JOIN customers c ON c.id = o.customer_id
WHERE o.ordered_at >= '2025-06-01 10:00' AND o.ordered_at < '2025-06-01 11:00';

-- もう一度実行する（2 回目はページがメモリにあるので速い）
EXPLAIN (ANALYZE, BUFFERS)
SELECT o.id, c.name
FROM orders o
JOIN customers c ON c.id = o.customer_id
WHERE o.ordered_at >= '2025-06-01 10:00' AND o.ordered_at < '2025-06-01 11:00';

-- 読み方: actual time と rows は「1 ループあたり」、Buffers は「全ループの合計」
--   内側の総時間 ≒ actual time の終了時刻 × loops
--   内側の総ページ数 = Buffers（116 回 × 3 ページ = 348）

-- もう 1 つの例: 顧客ごとに注文数を数える相関サブクエリ（SubPlan）
-- 外側の 5 行それぞれについて、内側で orders を全件読む（customer_id にインデックスがないため）
--   内側の総時間 ≒ Aggregate の actual time の終了時刻 × loops（5 回）
--   Buffers は 5 回分の合計（orders 8197 ページ × 5 回 ≒ 4 万ページ）
EXPLAIN (ANALYZE, BUFFERS)
SELECT c.id, c.name,
       (SELECT count(*) FROM orders o WHERE o.customer_id = c.id) AS orders
FROM customers c
WHERE c.id <= 5;

-- 演習 S04-ex06: 1 日分の注文を顧客の地域別に数える。見積もりと実測のズレはどのノードで起きているか
EXPLAIN (ANALYZE, BUFFERS)
SELECT c.region, count(*)
FROM orders o
JOIN customers c ON c.id = o.customer_id
WHERE o.ordered_at >= '2025-06-01' AND o.ordered_at < '2025-06-02'
GROUP BY c.region;

-- ズレの理由: このデータでは、ある 1 日の注文の顧客は全員が同じ地域になる
--   注文 i の顧客 = 1 + (i * 7919 % 50000)、顧客の地域 = 顧客 id % 5
--   → 地域は (1 + 4i) % 5 で決まり、1 日分の注文 i は 365 おき（5 の倍数おき）なので i % 5 が全員同じ
SELECT (o.id % 5) AS id_mod_5, c.region, count(*)
FROM orders o JOIN customers c ON c.id = o.customer_id
WHERE o.ordered_at >= '2025-06-01' AND o.ordered_at < '2025-06-02'
GROUP BY 1, 2;

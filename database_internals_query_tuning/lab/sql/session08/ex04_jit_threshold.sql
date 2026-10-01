-- S08 練習問題の模範解答：JIT が働くかどうかはプランのコストと jit_above_cost で決まる
-- 並列ありのプラン（コスト約 71,000）は既定の jit_above_cost = 100000 を下回るので JIT されない。
-- しきい値を下げると並列プランでも JIT され、ワーカーごとにコンパイルされる（Functions の数が増える）
SET jit = on;

-- (1) 既定のしきい値
SHOW jit_above_cost;
EXPLAIN (ANALYZE)
SELECT o.status, count(*) AS lines, sum(oi.quantity * oi.unit_price) AS amount,
       avg(oi.quantity * oi.unit_price) AS avg_amount, max(oi.unit_price) AS max_price
FROM orders o JOIN order_items oi ON oi.order_id = o.id
GROUP BY o.status ORDER BY o.status;

-- (2) しきい値を 10000 に下げる（このセッションだけ）
SET jit_above_cost = 10000;
EXPLAIN (ANALYZE)
SELECT o.status, count(*) AS lines, sum(oi.quantity * oi.unit_price) AS amount,
       avg(oi.quantity * oi.unit_price) AS avg_amount, max(oi.unit_price) AS max_price
FROM orders o JOIN order_items oi ON oi.order_id = o.id
GROUP BY o.status ORDER BY o.status;

RESET jit_above_cost;
RESET jit;

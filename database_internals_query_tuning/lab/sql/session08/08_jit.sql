-- S08-08 JIT コンパイル：式の評価を実行時に機械語へコンパイルして速くしようとする仕組み
-- このサンドボックスはサーバー全体で jit = off にしてある（実測の時間にコンパイル時間を混ぜないため）。
-- SET jit = on はこのセッションの中だけ有効。JIT はプランのコストが jit_above_cost（既定 100000）を超えたときだけ働く
SHOW jit;
SHOW jit_above_cost;

SET jit = on;
SELECT pg_jit_available();

-- (1) 並列なし：全注文 × 全明細の集計はコストが 100000 を超えるので、JIT: ブロックが出る
SET max_parallel_workers_per_gather = 0;
EXPLAIN (ANALYZE, BUFFERS)
SELECT o.status,
       count(*) AS lines,
       sum(oi.quantity * oi.unit_price) AS amount,
       avg(oi.quantity * oi.unit_price) AS avg_amount,
       max(oi.unit_price) AS max_price
FROM orders o
JOIN order_items oi ON oi.order_id = o.id
GROUP BY o.status
ORDER BY o.status;

-- (2) 同じクエリを JIT なしで
SET jit = off;
EXPLAIN (ANALYZE, BUFFERS)
SELECT o.status,
       count(*) AS lines,
       sum(oi.quantity * oi.unit_price) AS amount,
       avg(oi.quantity * oi.unit_price) AS avg_amount,
       max(oi.unit_price) AS max_price
FROM orders o
JOIN order_items oi ON oi.order_id = o.id
GROUP BY o.status
ORDER BY o.status;
RESET max_parallel_workers_per_gather;

-- (3) 並列ありだと、プランのコストが jit_above_cost を下回り、jit = on でも JIT は使われない
SET jit = on;
EXPLAIN (ANALYZE, BUFFERS)
SELECT o.status,
       count(*) AS lines,
       sum(oi.quantity * oi.unit_price) AS amount,
       avg(oi.quantity * oi.unit_price) AS avg_amount,
       max(oi.unit_price) AS max_price
FROM orders o
JOIN order_items oi ON oi.order_id = o.id
GROUP BY o.status
ORDER BY o.status;
RESET jit;

-- (4) 結果（売上は cancelled 以外の行で見る）
SELECT o.status,
       count(*) AS lines,
       sum(oi.quantity * oi.unit_price) AS amount
FROM orders o
JOIN order_items oi ON oi.order_id = o.id
GROUP BY o.status
ORDER BY o.status;

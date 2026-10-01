-- セッション4-10: コストは秒ではない。設定値とページ数・行数から計算できる相対値
SHOW seq_page_cost;
SHOW cpu_tuple_cost;
SHOW cpu_operator_cost;

-- プランナが使うページ数と行数（VACUUM / ANALYZE が記録したもの）
SELECT relpages, reltuples FROM pg_class WHERE relname = 'orders';

-- 並列を切って、単純な Seq Scan のコストを見る
SET max_parallel_workers_per_gather = 0;

-- 条件なし: relpages × seq_page_cost + reltuples × cpu_tuple_cost
EXPLAIN SELECT * FROM orders;
SELECT relpages * current_setting('seq_page_cost')::float8
     + reltuples * current_setting('cpu_tuple_cost')::float8 AS seq_scan_cost
FROM pg_class WHERE relname = 'orders';

-- 条件 1 つ: 各行で比較演算を 1 回するので reltuples × cpu_operator_cost が加わる
EXPLAIN SELECT * FROM orders WHERE status = 'pending';
SELECT relpages * current_setting('seq_page_cost')::float8
     + reltuples * current_setting('cpu_tuple_cost')::float8
     + reltuples * current_setting('cpu_operator_cost')::float8 * 1 AS seq_scan_cost
FROM pg_class WHERE relname = 'orders';

-- 条件 2 つ: 比較演算 2 回分
EXPLAIN SELECT * FROM orders WHERE status = 'pending' AND customer_id = 1;
SELECT relpages * current_setting('seq_page_cost')::float8
     + reltuples * current_setting('cpu_tuple_cost')::float8
     + reltuples * current_setting('cpu_operator_cost')::float8 * 2 AS seq_scan_cost
FROM pg_class WHERE relname = 'orders';

RESET max_parallel_workers_per_gather;

-- 並列の Seq Scan は「1 ワーカーあたりの行数」で CPU の分を割り引く（2 ワーカー + リーダーの手伝い 0.4 = 2.4 で割る）
--   8197 + (1000000 / 2.4) × (0.01 + 0.0025 × 演算子の数)
-- ordered_at::date = '2025-06-01' は「型変換」と「=」の 2 演算 → 8197 + 416666.67 × 0.015 = 14447
EXPLAIN SELECT * FROM orders WHERE ordered_at::date = '2025-06-01';
SELECT round(8197 + (1000000 / 2.4) * (0.01 + 0.0025 * 2), 2) AS parallel_seq_scan_cost;

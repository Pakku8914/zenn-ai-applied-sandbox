-- 演習 S04-ex09: Gather のコストの内訳（並列処理の準備と、ワーカーから行を受け取る費用）
--   Gather の総コスト = 子（Parallel Seq Scan）の総コスト + parallel_setup_cost + parallel_tuple_cost × 見積もり行数
SHOW parallel_setup_cost;
SHOW parallel_tuple_cost;
EXPLAIN SELECT * FROM orders WHERE ordered_at::date = '2025-06-01';
SELECT 14447.00 + 1000 + 0.1 * 5000 AS gather_total_cost;

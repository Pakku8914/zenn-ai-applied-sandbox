-- S08 練習問題の模範解答：深い OFFSET のページングは Top-N ソートの効きを失う
-- 「金額の大きい順に 10 件ずつ表示する画面」で、1 ページ目・1,001 ページ目・10,001 ページ目を開く
SET max_parallel_workers_per_gather = 0;

-- (1) 1 ページ目
EXPLAIN (ANALYZE, TIMING OFF)
SELECT id, order_id, quantity * unit_price AS amount FROM order_items
ORDER BY amount DESC, id LIMIT 10;

-- (2) 1,001 ページ目（OFFSET 10000）：上位 10,010 件をヒープで持つ
EXPLAIN (ANALYZE, TIMING OFF)
SELECT id, order_id, quantity * unit_price AS amount FROM order_items
ORDER BY amount DESC, id LIMIT 10 OFFSET 10000;

-- (3) 10,001 ページ目（OFFSET 100000）：上位 100,010 件は work_mem に収まらず、全件の外部ソートに戻る
EXPLAIN (ANALYZE, TIMING OFF)
SELECT id, order_id, quantity * unit_price AS amount FROM order_items
ORDER BY amount DESC, id LIMIT 10 OFFSET 100000;

-- (4) 解決策の例：前のページの最後の行（金額と id）を覚えておき、その「続き」から 10 件を読む（キーセットページネーション）。
--     (3) のページの直前の行（100,000 件目）は amount = 2601, id = 1666191。アプリが前ページの結果から渡す想定
--     金額の大きい順・同額なら id の小さい順、の「続き」は (amount, -id) < (2601, -1666191) と書ける
EXPLAIN (ANALYZE, TIMING OFF)
SELECT id, order_id, quantity * unit_price AS amount FROM order_items
WHERE (quantity * unit_price, -id) < (2601, -1666191)
ORDER BY amount DESC, id LIMIT 10;

-- (5) (3) と (4) が同じ 10 行を返すことを確かめる（差が 0 行なら一致）
SELECT count(*) AS diff_rows FROM (
  (SELECT id FROM order_items ORDER BY quantity * unit_price DESC, id LIMIT 10 OFFSET 100000)
  EXCEPT
  (SELECT id FROM order_items WHERE (quantity * unit_price, -id) < (2601, -1666191)
   ORDER BY quantity * unit_price DESC, id LIMIT 10)
) AS d;

RESET max_parallel_workers_per_gather;

-- S08-01 200万行の order_items を金額（quantity * unit_price）の大きい順に並べる
-- 先に出発点へ戻しておく: docker compose exec lab bash tools/reset.sh
-- EXPLAIN ANALYZE は結果の行を画面に返さないので、200万行を表示せずにソートだけを実行できる

-- (1) このサンドボックスの work_mem は意図的に小さい 8MB
SHOW work_mem;

-- (2) 既定のまま：Sort Method が external merge（一時ファイルを使う外部ソート）になる
EXPLAIN (ANALYZE, BUFFERS)
SELECT id, order_id, quantity * unit_price AS amount
FROM order_items
ORDER BY amount DESC, id;

-- (3) 上位 3 行だけ確認する（同じ金額の中は id 順）
SELECT id, order_id, quantity * unit_price AS amount
FROM order_items
ORDER BY amount DESC, id
LIMIT 3;

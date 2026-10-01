-- 選択率によってプランナの選択が変わることを確かめる。
-- customers.region は 5 地域に均等（1 地域 = 20%）、customers.id は主キー（1 行）。
-- 前提: 01_create_indexes.sql 実行済み

-- (1) 選択率 20%: region で 1 地域に絞る
EXPLAIN (ANALYZE, BUFFERS)
SELECT * FROM customers WHERE region = '東京';

-- (2) 選択率 0.002%: 主キーで 1 行に絞る
EXPLAIN (ANALYZE, BUFFERS)
SELECT * FROM customers WHERE id = 12345;

-- (3) 選択率を 40% → 60% に上げていく
EXPLAIN (ANALYZE, BUFFERS)
SELECT * FROM customers WHERE region IN ('東京', '大阪');

EXPLAIN (ANALYZE, BUFFERS)
SELECT * FROM customers WHERE region IN ('東京', '大阪', '名古屋');

-- (4) 比較のため (1) を Seq Scan に強制する（学習用。本番で enable_* を切り替えない）
SET enable_bitmapscan = off;
SET enable_indexscan = off;
EXPLAIN (ANALYZE, BUFFERS)
SELECT * FROM customers WHERE region = '東京';
RESET enable_bitmapscan;
RESET enable_indexscan;

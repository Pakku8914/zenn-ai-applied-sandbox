-- S08-03 集約の 2 方式：HashAggregate（ハッシュ表でまとめる）と GroupAggregate（並んだ入力を順にまとめる）
-- 題材は「注文ごとの金額合計」。グループは 100万個（注文の数）できる

-- (1) 既定：HashAggregate。ハッシュ表が上限を超え、ディスクに退避する（Batches / Disk Usage）
EXPLAIN (ANALYZE, BUFFERS)
SELECT order_id, sum(quantity * unit_price) AS amount
FROM order_items
GROUP BY order_id;

-- (2) ハッシュ表の上限は work_mem × hash_mem_multiplier。hash_mem_multiplier を 1 にすると上限が work_mem ちょうどになる
SHOW hash_mem_multiplier;
SET hash_mem_multiplier = 1;
EXPLAIN (ANALYZE, BUFFERS)
SELECT order_id, sum(quantity * unit_price) AS amount
FROM order_items
GROUP BY order_id;
RESET hash_mem_multiplier;

-- (3) work_mem を 64MB にすると、ハッシュ表が 1 回で収まる（Batches: 1）
SET work_mem = '64MB';
EXPLAIN (ANALYZE, BUFFERS)
SELECT order_id, sum(quantity * unit_price) AS amount
FROM order_items
GROUP BY order_id;
RESET work_mem;

-- (4) HashAggregate を禁止すると、Sort で order_id 順に並べてから GroupAggregate でまとめる
SET enable_hashagg = off;
EXPLAIN (ANALYZE, BUFFERS)
SELECT order_id, sum(quantity * unit_price) AS amount
FROM order_items
GROUP BY order_id;
RESET enable_hashagg;

-- (5) グループが少なければ（商品 5,000 種類）、ハッシュ表は小さくメモリに収まる
EXPLAIN (ANALYZE, BUFFERS)
SELECT product_id, sum(quantity * unit_price) AS amount
FROM order_items
GROUP BY product_id;

-- (6) order_id のインデックスがあれば、インデックス順に読むだけで「並んだ入力」になり、Sort なしの GroupAggregate が選ばれる
CREATE INDEX order_items_order_id_idx ON order_items (order_id);
EXPLAIN (ANALYZE, BUFFERS)
SELECT order_id, sum(quantity * unit_price) AS amount
FROM order_items
GROUP BY order_id;

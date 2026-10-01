-- S16-05 パーティションの制約：主キー・一意制約にはパーティションキーを含めなければならない
-- 01_range_partition.sql の後に実行する

-- (1) id だけの主キーは作れない（各パーティションの中でしか一意性を確かめられないため）
ALTER TABLE s16_orders ADD PRIMARY KEY (id);

-- (2) パーティションキーを含めれば作れる
ALTER TABLE s16_orders ADD PRIMARY KEY (id, ordered_at);

-- (3) ただし「id だけで一意」は保証されなくなる。別の月なら同じ id を入れられてしまう
BEGIN;
INSERT INTO s16_orders SELECT id, customer_id, ordered_at + interval '1 month', status FROM s16_orders WHERE id = 500000;
SELECT tableoid::regclass AS partition, id, ordered_at FROM s16_orders WHERE id = 500000 ORDER BY ordered_at;
ROLLBACK;

-- (4) id だけで引くと、主キーのインデックスがあっても12個すべてのパーティションを探す
EXPLAIN (ANALYZE, COSTS OFF)
SELECT * FROM s16_orders WHERE id = 500000;

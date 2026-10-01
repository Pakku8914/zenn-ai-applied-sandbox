-- S16-07 リストパーティションとハッシュパーティション
-- 先に出発点へ戻しておく: docker compose exec lab bash tools/reset.sh（01 は不要）

-- (1) リスト：status の値ごとに分ける
DROP TABLE IF EXISTS s16_orders_by_status;
CREATE TABLE s16_orders_by_status (LIKE orders) PARTITION BY LIST (status);
CREATE TABLE s16_orders_by_status_completed PARTITION OF s16_orders_by_status FOR VALUES IN ('completed');
CREATE TABLE s16_orders_by_status_pending   PARTITION OF s16_orders_by_status FOR VALUES IN ('pending');
CREATE TABLE s16_orders_by_status_cancelled PARTITION OF s16_orders_by_status FOR VALUES IN ('cancelled');
INSERT INTO s16_orders_by_status SELECT * FROM orders;
VACUUM ANALYZE s16_orders_by_status;

SELECT tableoid::regclass AS partition, count(*) AS rows FROM s16_orders_by_status GROUP BY tableoid ORDER BY partition;
EXPLAIN (ANALYZE, COSTS OFF)
SELECT count(*) FROM s16_orders_by_status WHERE status = 'cancelled';

-- (2) ハッシュ：customer_id のハッシュ値を 4 で割った余りで分ける（大きさをそろえたいとき）
DROP TABLE IF EXISTS s16_orders_by_customer;
CREATE TABLE s16_orders_by_customer (LIKE orders) PARTITION BY HASH (customer_id);
CREATE TABLE s16_orders_by_customer_0 PARTITION OF s16_orders_by_customer FOR VALUES WITH (MODULUS 4, REMAINDER 0);
CREATE TABLE s16_orders_by_customer_1 PARTITION OF s16_orders_by_customer FOR VALUES WITH (MODULUS 4, REMAINDER 1);
CREATE TABLE s16_orders_by_customer_2 PARTITION OF s16_orders_by_customer FOR VALUES WITH (MODULUS 4, REMAINDER 2);
CREATE TABLE s16_orders_by_customer_3 PARTITION OF s16_orders_by_customer FOR VALUES WITH (MODULUS 4, REMAINDER 3);
INSERT INTO s16_orders_by_customer SELECT * FROM orders;
VACUUM ANALYZE s16_orders_by_customer;

SELECT tableoid::regclass AS partition, count(*) AS rows FROM s16_orders_by_customer GROUP BY tableoid ORDER BY partition;
-- 等値条件なら1つに絞れる
EXPLAIN (ANALYZE, COSTS OFF)
SELECT count(*) FROM s16_orders_by_customer WHERE customer_id = 777;
-- 範囲条件ではハッシュの行き先が決まらないので絞れない
EXPLAIN (ANALYZE, COSTS OFF)
SELECT count(*) FROM s16_orders_by_customer WHERE customer_id BETWEEN 777 AND 780;

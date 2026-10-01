-- S16-11 MySQL のパーティション（本文末尾の「MySQL ではどうなるか」用）
-- docker compose exec -T lab mysql --skip-ssl -h mysql -ulab shopdb -t --force < sql/session16/11_mysql_partition.sql
-- （(1)(2) はエラーになるのが正しい。--force を付けるとエラーの後も続きを実行する）

-- (1) MySQL でも、主キー・一意キーにはパーティションに使う列を含めなければならない
DROP TABLE IF EXISTS s16_orders;
CREATE TABLE s16_orders (
    id BIGINT NOT NULL, customer_id INT NOT NULL, ordered_at DATETIME NOT NULL, status VARCHAR(10) NOT NULL,
    PRIMARY KEY (id)
) PARTITION BY RANGE COLUMNS (ordered_at) (
    PARTITION p2025_01 VALUES LESS THAN ('2025-02-01'),
    PARTITION pmax VALUES LESS THAN (MAXVALUE)
);

-- (2) InnoDB のパーティション表は外部キーを持てない
CREATE TABLE s16_orders (
    id BIGINT NOT NULL, customer_id INT NOT NULL, ordered_at DATETIME NOT NULL, status VARCHAR(10) NOT NULL,
    PRIMARY KEY (id, ordered_at),
    FOREIGN KEY (customer_id) REFERENCES customers (id)
) PARTITION BY RANGE COLUMNS (ordered_at) (
    PARTITION p2025_01 VALUES LESS THAN ('2025-02-01'),
    PARTITION pmax VALUES LESS THAN (MAXVALUE)
);

-- (3) 主キーに ordered_at を含め、外部キーを付けなければ作れる。月ごとに12個
CREATE TABLE s16_orders (
    id BIGINT NOT NULL, customer_id INT NOT NULL, ordered_at DATETIME NOT NULL, status VARCHAR(10) NOT NULL,
    PRIMARY KEY (id, ordered_at)
) PARTITION BY RANGE COLUMNS (ordered_at) (
    PARTITION p2025_01 VALUES LESS THAN ('2025-02-01'),
    PARTITION p2025_02 VALUES LESS THAN ('2025-03-01'),
    PARTITION p2025_03 VALUES LESS THAN ('2025-04-01'),
    PARTITION p2025_04 VALUES LESS THAN ('2025-05-01'),
    PARTITION p2025_05 VALUES LESS THAN ('2025-06-01'),
    PARTITION p2025_06 VALUES LESS THAN ('2025-07-01'),
    PARTITION p2025_07 VALUES LESS THAN ('2025-08-01'),
    PARTITION p2025_08 VALUES LESS THAN ('2025-09-01'),
    PARTITION p2025_09 VALUES LESS THAN ('2025-10-01'),
    PARTITION p2025_10 VALUES LESS THAN ('2025-11-01'),
    PARTITION p2025_11 VALUES LESS THAN ('2025-12-01'),
    PARTITION p2025_12 VALUES LESS THAN ('2026-01-01')
);
-- 大きなトランザクションを避けるため、25万行ずつ入れる
INSERT INTO s16_orders SELECT id, customer_id, ordered_at, status FROM orders WHERE id BETWEEN 1 AND 250000;
INSERT INTO s16_orders SELECT id, customer_id, ordered_at, status FROM orders WHERE id BETWEEN 250001 AND 500000;
INSERT INTO s16_orders SELECT id, customer_id, ordered_at, status FROM orders WHERE id BETWEEN 500001 AND 750000;
INSERT INTO s16_orders SELECT id, customer_id, ordered_at, status FROM orders WHERE id BETWEEN 750001 AND 1000000;
ANALYZE TABLE s16_orders;

-- (4) 表形式の EXPLAIN の partitions 列に、読むパーティションが出る
EXPLAIN FORMAT=TRADITIONAL
SELECT COUNT(*) FROM s16_orders WHERE ordered_at >= '2025-06-01' AND ordered_at < '2025-07-01';
EXPLAIN FORMAT=TRADITIONAL
SELECT COUNT(*) FROM s16_orders WHERE DATE(ordered_at) BETWEEN '2025-06-01' AND '2025-06-30';

-- (5) 古い月の削除は DROP PARTITION（ALTER TABLE の一部として行う）
ALTER TABLE s16_orders DROP PARTITION p2025_01;
SELECT COUNT(*) FROM s16_orders;

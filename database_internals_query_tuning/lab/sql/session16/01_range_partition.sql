-- S16-01 orders を ordered_at の月次レンジパーティションに作り替える（作業用テーブル s16_orders）
-- 先に出発点へ戻しておく: docker compose exec lab bash tools/reset.sh
-- 境界の日時はセッションのタイムゾーン（このサンドボックスは UTC）で解釈される
DROP TABLE IF EXISTS s16_orders;
CREATE TABLE s16_orders (
    id           bigint       NOT NULL,
    customer_id  integer      NOT NULL,
    ordered_at   timestamptz  NOT NULL,
    status       text         NOT NULL
) PARTITION BY RANGE (ordered_at);

-- 1か月に1つずつ、12個のパーティション（上限は「その値を含まない」）
CREATE TABLE s16_orders_2025_01 PARTITION OF s16_orders FOR VALUES FROM ('2025-01-01') TO ('2025-02-01');
CREATE TABLE s16_orders_2025_02 PARTITION OF s16_orders FOR VALUES FROM ('2025-02-01') TO ('2025-03-01');
CREATE TABLE s16_orders_2025_03 PARTITION OF s16_orders FOR VALUES FROM ('2025-03-01') TO ('2025-04-01');
CREATE TABLE s16_orders_2025_04 PARTITION OF s16_orders FOR VALUES FROM ('2025-04-01') TO ('2025-05-01');
CREATE TABLE s16_orders_2025_05 PARTITION OF s16_orders FOR VALUES FROM ('2025-05-01') TO ('2025-06-01');
CREATE TABLE s16_orders_2025_06 PARTITION OF s16_orders FOR VALUES FROM ('2025-06-01') TO ('2025-07-01');
CREATE TABLE s16_orders_2025_07 PARTITION OF s16_orders FOR VALUES FROM ('2025-07-01') TO ('2025-08-01');
CREATE TABLE s16_orders_2025_08 PARTITION OF s16_orders FOR VALUES FROM ('2025-08-01') TO ('2025-09-01');
CREATE TABLE s16_orders_2025_09 PARTITION OF s16_orders FOR VALUES FROM ('2025-09-01') TO ('2025-10-01');
CREATE TABLE s16_orders_2025_10 PARTITION OF s16_orders FOR VALUES FROM ('2025-10-01') TO ('2025-11-01');
CREATE TABLE s16_orders_2025_11 PARTITION OF s16_orders FOR VALUES FROM ('2025-11-01') TO ('2025-12-01');
CREATE TABLE s16_orders_2025_12 PARTITION OF s16_orders FOR VALUES FROM ('2025-12-01') TO ('2026-01-01');

-- orders の 100 万行を入れる。行は ordered_at に応じて各パーティションへ振り分けられる
INSERT INTO s16_orders SELECT id, customer_id, ordered_at, status FROM orders;
VACUUM ANALYZE s16_orders;

-- パーティションごとの行数とページ数（tableoid は行が実際に入っているテーブル）
SELECT tableoid::regclass AS partition, count(*) AS rows,
       pg_relation_size(tableoid) / 8192 AS pages
FROM s16_orders
GROUP BY tableoid
ORDER BY partition;

-- \d+ でパーティションの一覧と境界を見る
\d+ s16_orders

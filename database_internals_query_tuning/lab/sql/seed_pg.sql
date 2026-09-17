-- 決定的なデータ投入（乱数を使わないので何度実行しても同じ内容になる）。
-- 素数を掛けた剰余で分布を散らしている。本文の行数・実行計画と一致させるため式を変えないこと。
BEGIN;

TRUNCATE order_items, orders, products, customers RESTART IDENTITY;

INSERT INTO customers (id, name, email, region, created_at)
SELECT i,
       '顧客' || i,
       'user' || i || '@example.com',
       (ARRAY['東京', '大阪', '名古屋', '福岡', '札幌'])[1 + (i % 5)],
       TIMESTAMPTZ '2024-01-01 00:00:00+00' + ((i % 700) || ' days')::interval
FROM generate_series(1, 50000) AS s(i);

INSERT INTO products (id, name, category, price, stock)
SELECT i,
       '商品' || i,
       (ARRAY['文具', '書籍', '雑貨', '食品'])[1 + (i % 4)],
       100 + (i * 37 % 9900),
       (i * 13 % 500)
FROM generate_series(1, 5000) AS s(i);

INSERT INTO orders (id, customer_id, ordered_at, status)
SELECT i,
       1 + ((i::bigint * 7919) % 50000)::int,
       TIMESTAMPTZ '2025-01-01 00:00:00+00'
         + ((i % 365) || ' days')::interval
         + (((i::bigint * 61) % 86400) || ' seconds')::interval,
       CASE WHEN i % 23 = 0 THEN 'cancelled'
            WHEN i % 7 = 0  THEN 'pending'
            ELSE 'completed' END
FROM generate_series(1, 1000000) AS s(i);

INSERT INTO order_items (order_id, product_id, quantity, unit_price)
SELECT o.i,
       1 + ((o.i::bigint * 104729 + k.k) % 5000)::int,
       1 + ((o.i + k.k) % 3),
       100 + ((o.i::bigint * 31 + k.k) % 900)::int
FROM generate_series(1, 1000000) AS o(i)
CROSS JOIN generate_series(0, 2) AS k(k)
WHERE k.k <= (o.i % 3);

COMMIT;

-- プランナが正しい統計で判断できるようにする（統計がないと本文の実行計画が再現しない）
VACUUM (ANALYZE) customers, products, orders, order_items;

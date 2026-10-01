-- S09-05 式インデックス：関数を掛けた列を救う。作った後に ANALYZE が要る理由
-- 題材は Mid01 の遅いクエリ A（書き換える前の lower(email) のまま）。出発点から実行する

CREATE INDEX orders_customer_id_idx ON orders (customer_id);

-- (1) lower(email) の式インデックスを作る。この時点では式の統計はまだ無い
CREATE INDEX customers_lower_email_idx ON customers (lower(email));
SELECT count(*) AS expression_stats
FROM pg_stats
WHERE tablename = 'customers_lower_email_idx';

-- (2) インデックスは使われるが、見積もりは既定の 0.5%（250 行）のまま → orders 側は Hash Join ＋ 全件読み
EXPLAIN (ANALYZE, BUFFERS)
SELECT o.id, o.ordered_at, o.status
FROM customers c
JOIN orders o ON o.customer_id = c.id
WHERE lower(c.email) = lower('User12345@Example.com')
ORDER BY o.ordered_at DESC;

-- (3) ANALYZE すると、式インデックスの「式」の統計が作られる（tablename にインデックス名が入る）
ANALYZE customers;
SELECT tablename, attname, n_distinct
FROM pg_stats
WHERE tablename = 'customers_lower_email_idx';

-- 見積もりが 1 行になり、orders_customer_id_idx を引く Nested Loop に変わる
EXPLAIN (ANALYZE, BUFFERS)
SELECT o.id, o.ordered_at, o.status
FROM customers c
JOIN orders o ON o.customer_id = c.id
WHERE lower(c.email) = lower('User12345@Example.com')
ORDER BY o.ordered_at DESC;

-- (4) timestamptz を date に変換する式はそのままでは索引にできない（タイムゾーン設定で結果が変わるため）
--     次の文はエラーになる（想定どおり）
CREATE INDEX orders_ordered_date_idx ON orders ((ordered_at::date));

-- (5) タイムゾーンを式の中で固定すれば作れる。ただしクエリも同じ式で書かないと使われない
CREATE INDEX orders_ordered_date_utc_idx ON orders (((ordered_at AT TIME ZONE 'UTC')::date));
ANALYZE orders;
EXPLAIN
SELECT count(*) FROM orders WHERE (ordered_at AT TIME ZONE 'UTC')::date = DATE '2025-06-01';
EXPLAIN
SELECT count(*) FROM orders WHERE ordered_at::date = DATE '2025-06-01';
SELECT pg_size_pretty(pg_relation_size('orders_ordered_date_utc_idx')) AS utc_date_index;

-- 後片付け
DROP INDEX orders_customer_id_idx, customers_lower_email_idx, orders_ordered_date_utc_idx;

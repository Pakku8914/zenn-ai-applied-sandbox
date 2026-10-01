-- S09-08 B-tree 以外の索引：BRIN・GIN・GiST（各 1 例）
-- 出発点から実行する

-- ===== BRIN：物理順と相関のある列にだけ効く、極端に小さい索引 =====
-- (1) 物理順との相関（1 に近いほど、値の順に行が並んでいる）
SELECT attname, correlation
FROM pg_stats
WHERE tablename = 'orders' AND attname IN ('id', 'ordered_at')
ORDER BY attname;

CREATE INDEX orders_id_brin ON orders USING brin (id);
CREATE INDEX orders_ordered_at_brin ON orders USING brin (ordered_at);
SELECT indexrelid::regclass AS index_name,
       pg_size_pretty(pg_relation_size(indexrelid)) AS size,
       pg_relation_size(indexrelid) / 8192 AS pages
FROM pg_index
WHERE indrelid = 'orders'::regclass
ORDER BY pg_relation_size(indexrelid), index_name;

-- (2) id の範囲（1 万行）：B-tree の主キーを使わせないようにして BRIN を試す。読むのは 128 ページだけ
SET enable_indexscan = off;
SET enable_indexonlyscan = off;
EXPLAIN (ANALYZE, BUFFERS)
SELECT count(*) FROM orders WHERE id BETWEEN 500000 AND 509999;
RESET enable_indexscan;
RESET enable_indexonlyscan;

-- (3) ordered_at の 1 日：プランナは BRIN を選ばない。Seq Scan を禁止して使わせると、全ページが候補になる
EXPLAIN (ANALYZE, BUFFERS)
SELECT count(*) FROM orders WHERE ordered_at >= '2025-06-01' AND ordered_at < '2025-06-02';
SET enable_seqscan = off;
EXPLAIN (ANALYZE, BUFFERS)
SELECT count(*) FROM orders WHERE ordered_at >= '2025-06-01' AND ordered_at < '2025-06-02';
RESET enable_seqscan;
DROP INDEX orders_id_brin, orders_ordered_at_brin;

-- ===== GIN：配列（や全文検索）の「要素を含むか」を引く =====
-- 作業用テーブル：注文 20 万件について、含まれる商品番号を配列にまとめる
CREATE TABLE s09_order_products AS
SELECT oi.order_id, array_agg(oi.product_id ORDER BY oi.product_id) AS product_ids
FROM order_items oi
WHERE oi.order_id <= 200000
GROUP BY oi.order_id;
VACUUM (ANALYZE) s09_order_products;

-- (4) 商品 1234 を含む注文：B-tree では引けない条件なので全件読み
EXPLAIN (ANALYZE, BUFFERS)
SELECT count(*) FROM s09_order_products WHERE product_ids @> ARRAY[1234];

-- (5) GIN を作ると Bitmap Index Scan で引ける。2 つの商品を両方含む注文も同じ索引で引ける
CREATE INDEX s09_order_products_gin ON s09_order_products USING gin (product_ids);
EXPLAIN (ANALYZE, BUFFERS)
SELECT count(*) FROM s09_order_products WHERE product_ids @> ARRAY[1234];
EXPLAIN (ANALYZE, BUFFERS)
SELECT count(*) FROM s09_order_products WHERE product_ids @> ARRAY[1234, 1235];
SELECT pg_size_pretty(pg_relation_size('s09_order_products')) AS heap,
       pg_size_pretty(pg_relation_size('s09_order_products_gin')) AS gin;

-- ===== GiST：範囲型の「重なる・含む」を引く =====
-- 作業用テーブル：注文 20 万件の配達予定時間帯（翌日、1〜4 時間の幅）
CREATE TABLE s09_deliveries AS
SELECT id AS order_id,
       tstzrange(ordered_at + interval '1 day',
                 ordered_at + interval '1 day' + ((1 + id % 4) || ' hours')::interval) AS delivery_window
FROM orders
WHERE id <= 200000;
VACUUM (ANALYZE) s09_deliveries;

-- (6) 2025-06-02 12:00 に配達予定時間帯に入っている注文：索引が無いので全件読み
EXPLAIN (ANALYZE, BUFFERS)
SELECT count(*) FROM s09_deliveries WHERE delivery_window @> timestamptz '2025-06-02 12:00+00';

-- (7) GiST を作ると範囲の「含む（@>）」「重なる（&&）」を索引で引ける
CREATE INDEX s09_deliveries_window_gist ON s09_deliveries USING gist (delivery_window);
EXPLAIN (ANALYZE, BUFFERS)
SELECT count(*) FROM s09_deliveries WHERE delivery_window @> timestamptz '2025-06-02 12:00+00';
EXPLAIN (ANALYZE, BUFFERS)
SELECT count(*) FROM s09_deliveries
WHERE delivery_window && tstzrange('2025-06-02 12:00+00', '2025-06-02 13:00+00');

-- (8) GiST は「期間が重ならない」制約（排他制約）にも使われる。2 行目はエラーになる（想定どおり）
CREATE TABLE s09_sale_periods (
    name   text      NOT NULL,
    period tstzrange NOT NULL,
    EXCLUDE USING gist (period WITH &&)
);
INSERT INTO s09_sale_periods VALUES ('夏のセール', tstzrange('2025-07-01', '2025-07-15'));
INSERT INTO s09_sale_periods VALUES ('お盆セール', tstzrange('2025-07-10', '2025-07-20'));

-- 後片付け
DROP TABLE s09_order_products, s09_deliveries, s09_sale_periods;

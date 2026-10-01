-- Final-10 インデックス設計を 1 セット入れる：3 本を足し、使われていない 1 本を消す（10 秒ほど）
-- 01〜09 の後に実行する。作る前後で「インデックスの合計サイズ」を比べる

-- (1) 作る前のインデックスの大きさ（主キーと、もともとある orders_status_idx）
SELECT t.relname AS table_name, i.relname AS index_name,
       pg_size_pretty(pg_relation_size(i.oid)) AS size
FROM pg_index x
JOIN pg_class i ON i.oid = x.indexrelid
JOIN pg_class t ON t.oid = x.indrelid
WHERE t.relname IN ('orders', 'order_items', 'final_ship_queue')
ORDER BY t.relname, i.relname;
SELECT pg_size_pretty(sum(pg_relation_size(x.indexrelid))) AS index_total
FROM pg_index x JOIN pg_class t ON t.oid = x.indrelid
WHERE t.relname IN ('orders', 'order_items', 'final_ship_queue');

-- (2) 足す 3 本
-- Q1：顧客の注文を探す。1 人 20 件しかないので、並べ替えのための複合インデックスにはしない
CREATE INDEX orders_customer_id_idx ON orders (customer_id);
-- Q1・Q4：注文から明細を引く（外部キー側）。Q4 が明細の 3 列を読むので INCLUDE でカバリングにする
CREATE INDEX order_items_order_id_idx ON order_items (order_id) INCLUDE (product_id, quantity, unit_price);
-- Q3：地域ごとに古い順。等値の列（region）を先、並べ替えの列（ordered_at）を後にする
CREATE INDEX final_ship_queue_region_ordered_at_idx ON final_ship_queue (region, ordered_at);
-- （Q4 の「直近 7 日」のための orders (ordered_at) は、Q5 の計画を変えて遅くするので入れない。ex03 で確かめる）

-- (3) 使われていない 1 本を消す（09 で idx_scan = 0 を確かめた）
DROP INDEX orders_status_idx;

-- (4) 作った後のインデックスの大きさ
SELECT t.relname AS table_name, i.relname AS index_name,
       pg_size_pretty(pg_relation_size(i.oid)) AS size
FROM pg_index x
JOIN pg_class i ON i.oid = x.indexrelid
JOIN pg_class t ON t.oid = x.indrelid
WHERE t.relname IN ('orders', 'order_items', 'final_ship_queue')
ORDER BY t.relname, i.relname;
SELECT pg_size_pretty(sum(pg_relation_size(x.indexrelid))) AS index_total
FROM pg_index x JOIN pg_class t ON t.oid = x.indrelid
WHERE t.relname IN ('orders', 'order_items', 'final_ship_queue');

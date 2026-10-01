-- R03-03 営業時間中のインデックス作成：CREATE INDEX と CREATE INDEX CONCURRENTLY の所要時間、失敗したときの後始末
-- \i sql/review03/03_create_index_concurrently.sql（01 の後）
\timing on
-- (1) 普通の CREATE INDEX（作っている間は書き込みが止まる：ShareLock）
CREATE INDEX r03_orders_customer_idx ON r03_orders (customer_id);
DROP INDEX r03_orders_customer_idx;
-- (2) CONCURRENTLY（書き込みを止めないが、テーブルを 2 回読むぶん時間がかかる）
CREATE INDEX CONCURRENTLY r03_orders_customer_idx ON r03_orders (customer_id);
DROP INDEX r03_orders_customer_idx;
\timing off

-- (3) CONCURRENTLY が途中で失敗すると、使えない（INVALID）インデックスが残る。
--     customer_id は重複しているので、UNIQUE にしようとすると失敗する
CREATE UNIQUE INDEX CONCURRENTLY r03_orders_customer_uniq ON r03_orders (customer_id);
SELECT indexrelid::regclass AS index, indisvalid, indisready, pg_size_pretty(pg_relation_size(indexrelid)) AS size
FROM pg_index WHERE indrelid = 'r03_orders'::regclass ORDER BY 1::text;
-- INVALID なインデックスはクエリには使われない。失敗した段階によっては indisready = t のまま残り、書き込みのたびに更新の負担だけがかかる（ここでは indisready = f）。消してから作り直す
DROP INDEX CONCURRENTLY r03_orders_customer_uniq;
-- (4) CONCURRENTLY なしの CREATE UNIQUE INDEX は、失敗すると何も残らない（トランザクションごと取り消される）
CREATE UNIQUE INDEX r03_orders_customer_uniq ON r03_orders (customer_id);
SELECT indexrelid::regclass AS index, indisvalid FROM pg_index WHERE indrelid = 'r03_orders'::regclass ORDER BY 1::text;

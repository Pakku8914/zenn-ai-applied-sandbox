-- R03-10 使われていないインデックスを見つけて、書き込みを止めずに消す（S09 の復習）
-- \i sql/review03/10_unused_index.sql（01 から作り直すので 10 秒ほど）
\i sql/review03/01_setup.sql
CREATE INDEX r03_orders_customer_idx ON r03_orders (customer_id);
CREATE INDEX r03_orders_ordered_at_idx ON r03_orders (ordered_at);

-- 顧客別の注文を 3 回引く（customer_id のインデックスだけが使われる）
SELECT count(*) FROM r03_orders WHERE customer_id = 7920;
SELECT count(*) FROM r03_orders WHERE customer_id = 15839;
SELECT count(*) FROM r03_orders WHERE customer_id = 23758;
SELECT pg_stat_force_next_flush();

-- idx_scan = 0 でも、主キー・一意制約のインデックス（制約を守るために必要）は消してはいけない
SELECT s.indexrelname, s.idx_scan, i.indisprimary OR i.indisunique AS for_constraint,
       pg_size_pretty(pg_relation_size(s.indexrelid)) AS size
FROM pg_stat_user_indexes AS s JOIN pg_index AS i USING (indexrelid)
WHERE s.relname = 'r03_orders' ORDER BY s.indexrelname;

-- 制約のためでもなく一度も使われていないインデックスは、書き込みのたびに更新されるだけの荷物。CONCURRENTLY なら書き込みを止めずに消せる
DROP INDEX CONCURRENTLY r03_orders_ordered_at_idx;
SELECT indexrelname FROM pg_stat_user_indexes WHERE relname = 'r03_orders' ORDER BY indexrelname;

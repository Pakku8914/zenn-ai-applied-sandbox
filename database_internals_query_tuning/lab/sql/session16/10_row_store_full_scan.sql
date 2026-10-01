-- S16-10 行指向の限界：使う列が1つでも、行ごと全部のページを読む
-- 先に出発点へ戻しておく: docker compose exec lab bash tools/reset.sh

-- (1) 1年分の日次の注文件数。使うのは ordered_at（8バイト）だけだが、orders の全ページを読む
SET max_parallel_workers_per_gather = 0;
EXPLAIN (ANALYZE, BUFFERS)
SELECT (ordered_at AT TIME ZONE 'UTC')::date AS day, count(*)
FROM orders
GROUP BY day;

-- (2) 1行の大きさと、ordered_at 列の大きさ
SELECT avg(pg_column_size(o.*))::int AS avg_row_bytes,
       avg(pg_column_size(o.ordered_at))::int AS ordered_at_bytes,
       pg_relation_size('orders') / 8192 AS table_pages
FROM orders o;

-- (3) ordered_at だけのインデックスは、その列だけを抜き出した細い写しになる。
--     プランナは既定では Seq Scan を選ぶので、Seq Scan を止めて Index Only Scan が読むページ数を見る（比較のためだけの設定）
CREATE INDEX orders_ordered_at_idx ON orders (ordered_at);
VACUUM orders;
SET enable_seqscan = off;
EXPLAIN (ANALYZE, BUFFERS)
SELECT (ordered_at AT TIME ZONE 'UTC')::date AS day, count(*)
FROM orders
GROUP BY day;
RESET enable_seqscan;
RESET max_parallel_workers_per_gather;

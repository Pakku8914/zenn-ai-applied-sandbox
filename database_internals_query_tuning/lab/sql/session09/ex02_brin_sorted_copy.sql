-- S09-ex02 BRIN が効くように並べ直す：ordered_at の順に並べた作業用コピー
-- 出発点から実行する。元の orders では ordered_at の BRIN は全ページを候補にした（08 の (3)）

CREATE TABLE s09_orders_by_date AS SELECT * FROM orders ORDER BY ordered_at;
VACUUM (ANALYZE) s09_orders_by_date;
SELECT attname, correlation FROM pg_stats
WHERE tablename = 's09_orders_by_date' AND attname = 'ordered_at';

CREATE INDEX s09_orders_by_date_brin ON s09_orders_by_date USING brin (ordered_at);
EXPLAIN (ANALYZE, BUFFERS)
SELECT count(*) FROM s09_orders_by_date
WHERE ordered_at >= '2025-06-01' AND ordered_at < '2025-06-02';
SELECT pg_size_pretty(pg_relation_size('s09_orders_by_date_brin')) AS brin_size;

-- 後片付け
DROP TABLE s09_orders_by_date;

-- セッション3-2: ordered_at に B+木インデックスを作る
\timing on
CREATE INDEX orders_ordered_at_idx ON orders (ordered_at);
\timing off

-- インデックスもページの列。テーブル本体と大きさを比べる
SELECT c.relname,
       c.relkind,
       pg_relation_size(c.oid)                 AS bytes,
       pg_size_pretty(pg_relation_size(c.oid)) AS size,
       pg_relation_size(c.oid) / 8192          AS pages
FROM pg_class c
WHERE c.relname IN ('orders', 'orders_pkey', 'orders_ordered_at_idx')
ORDER BY c.relkind DESC, c.relname;

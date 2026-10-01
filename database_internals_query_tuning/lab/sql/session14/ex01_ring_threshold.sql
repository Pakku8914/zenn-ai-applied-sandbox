-- S14 演習1 どのテーブルの Seq Scan がリングバッファを使うか（共有バッファの 1/4 より大きいか）を判定する
-- \i sql/session14/ex01_ring_threshold.sql
SELECT c.relname, pg_relation_size(c.oid) / 8192 AS pages,
       current_setting('shared_buffers')::text AS shared_buffers,
       (SELECT setting::int FROM pg_settings WHERE name = 'shared_buffers') / 4 AS quarter_pages,
       pg_relation_size(c.oid) / 8192 > (SELECT setting::int FROM pg_settings WHERE name = 'shared_buffers') / 4 AS uses_ring
FROM pg_class c
WHERE c.relname IN ('customers', 'products', 'orders', 'order_items')
ORDER BY pages;

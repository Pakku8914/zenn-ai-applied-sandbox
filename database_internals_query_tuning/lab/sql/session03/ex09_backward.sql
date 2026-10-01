-- 演習 S03-ex09: 新しい順（DESC）の上位 10 件もインデックスで読めるか（02_create_index.sql の後に実行）
EXPLAIN (ANALYZE, BUFFERS) SELECT * FROM orders ORDER BY ordered_at DESC LIMIT 10;

-- セッション2（MySQL 比較）: InnoDB のページと行の並び
-- 使い方: docker compose exec -T lab mysql --skip-ssl -h mysql -ulab shopdb -t < sql/session02/mysql_01_innodb_pages.sql

-- InnoDB のページは既定 16KB（PostgreSQL は 8KB）
SELECT @@innodb_page_size;

-- テーブル本体（クラスタ化インデックス＝主キーの B+木）の大きさ。table_rows と avg_row_length は統計からの概算
SELECT table_name, table_rows, avg_row_length, data_length,
       data_length DIV @@innodb_page_size AS pages
FROM information_schema.tables
WHERE table_schema = DATABASE()
  AND table_name IN ('customers', 'products', 'orders', 'order_items')
ORDER BY data_length;

-- 行は主キーの順に並ぶ。UPDATE しても行の位置（主キーの順序）は変わらない
BEGIN;
UPDATE orders SET status = 'pending' WHERE id = 1;
SELECT * FROM orders LIMIT 3;
ROLLBACK;

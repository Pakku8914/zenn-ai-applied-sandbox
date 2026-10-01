-- S08-09 MySQL ではどうなるか（mysql クライアントで実行する）
-- docker compose exec lab mysql --skip-ssl -h mysql -ulab shopdb
-- mysql> source sql/session08/09_mysql_compare.sql
-- MySQL のソート用メモリは sort_buffer_size（ソート 1 回ごと・既定 256KB）。PostgreSQL の work_mem に近い役割

SELECT @@sort_buffer_size;

-- (1) LIMIT 付きのソート：上位 N 件だけを持つ（limit input to 10 row(s) per chunk）
EXPLAIN ANALYZE
SELECT id, order_id, quantity * unit_price AS amount
FROM order_items
ORDER BY amount DESC, id
LIMIT 10\G

-- (2) 全件のソート（200万行）：sort_buffer_size に収まらない分はマージを繰り返す。
--     回数はセッションの状態変数 Sort_merge_passes に数えられる（実行前後の差を見る）
--     派生テーブルの ORDER BY は LIMIT が無いと MySQL が取り除くので、全件数の LIMIT を付けてソートを残している
SHOW SESSION STATUS LIKE 'Sort_merge_passes';
SELECT COUNT(*), SUM(amount) FROM (
  SELECT id, order_id, quantity * unit_price AS amount FROM order_items ORDER BY amount DESC, id LIMIT 2000000
) AS s;
SHOW SESSION STATUS LIKE 'Sort_merge_passes';

-- (3) このセッションだけ sort_buffer_size を 128MB にして同じソート
SET SESSION sort_buffer_size = 128 * 1024 * 1024;
SELECT COUNT(*), SUM(amount) FROM (
  SELECT id, order_id, quantity * unit_price AS amount FROM order_items ORDER BY amount DESC, id LIMIT 2000000
) AS s;
SHOW SESSION STATUS LIKE 'Sort_merge_passes';
SET SESSION sort_buffer_size = DEFAULT;

-- (4) ウィンドウ関数：Sort の後に Window aggregate が来る形は PostgreSQL と同じ
EXPLAIN ANALYZE
SELECT COUNT(*) FROM (
  SELECT customer_id, id,
         ROW_NUMBER() OVER (PARTITION BY customer_id ORDER BY ordered_at) AS nth
  FROM orders
) AS s
WHERE nth = 1\G

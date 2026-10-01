-- Final-16 MySQL（InnoDB）ではどうなるか（mysql クライアントで実行する: docker compose exec lab mysql --skip-ssl -h mysql -ulab shopdb）
-- 前半（1）は 1 セッションで流してよい。後半（2）は【3セッション】で、見出しごとに書かれた側に貼る。
-- B1 でセッションBが止まる。解除：セッションAで COMMIT; か ROLLBACK; / innodb_lock_wait_timeout（秒）で B がエラーになる

-- (1) Q1 顧客の注文一覧。InnoDB は外部キーを張ると参照する側の列にインデックスを自動で作る（fk_orders_customer・fk_items_order）
SHOW INDEX FROM order_items WHERE Key_name <> 'PRIMARY';
EXPLAIN ANALYZE
SELECT o.id, o.ordered_at, o.status, count(*) AS items, sum(oi.quantity * oi.unit_price) AS amount
FROM orders o JOIN order_items oi ON oi.order_id = o.id
WHERE o.customer_id = 12345
GROUP BY o.id
ORDER BY o.ordered_at DESC
LIMIT 10\G

-- (2) 在庫引き当ての待ち。作業用の final_products を作る（何度実行してもよい）
DROP TABLE IF EXISTS final_products;
CREATE TABLE final_products (PRIMARY KEY (id)) AS
SELECT id, name, category, price, 100000 AS stock FROM products;

-- [A1] セッションA: 注文Xの引き当て。行ロックを取って決済 API の応答を待っている（まだ COMMIT しない）
BEGIN;
SELECT stock FROM final_products WHERE id = 777 FOR UPDATE;

-- [B1] セッションB: 同じ商品を引き当てようとする。2 秒待ってエラーになる（既定の innodb_lock_wait_timeout は 50 秒）
SET SESSION innodb_lock_wait_timeout = 2;
BEGIN;
SELECT stock FROM final_products WHERE id = 777 FOR UPDATE;

-- [C1] セッションC: B が待っている間に実行する（B1 を貼ってから 2 秒以内）。LOCK WAIT のトランザクションが見える
SELECT trx_mysql_thread_id AS thread, trx_state, trx_wait_started IS NOT NULL AS waiting, left(trx_query, 50) AS query
FROM information_schema.INNODB_TRX ORDER BY trx_started;

-- [B2] セッションB: 待たずに結果を返す書き方。NOWAIT はすぐエラー、SKIP LOCKED はロック中の行を飛ばす（0 行）
SELECT stock FROM final_products WHERE id = 777 FOR UPDATE NOWAIT;
SELECT stock FROM final_products WHERE id = 777 FOR UPDATE SKIP LOCKED;
ROLLBACK;

-- [A2] セッションA: 取り消す
ROLLBACK;

-- [B3] セッションB: 改善後の書き方（在庫が足りれば減らす 1 文 → すぐ COMMIT）は、MySQL でも同じように書ける
BEGIN;
UPDATE final_products SET stock = stock - 1 WHERE id = 777 AND stock >= 1;
SELECT ROW_COUNT() AS updated_rows;
COMMIT;
SELECT stock FROM final_products WHERE id = 777;

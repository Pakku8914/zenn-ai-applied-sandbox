-- S10-11 MySQL ではどうなるか（mysql クライアントで実行する）
-- 【2〜3セッション】ターミナルを開き、どれも docker compose exec lab mysql --skip-ssl -h mysql -ulab shopdb で入る。
-- 見出しごとに、書かれた側のセッションに貼る（source で一度に流さない）。
-- 途中でセッションBが止まる。セッションAの COMMIT / ROLLBACK で進む。
-- 待ち続けたくないときは、止まる前に SET innodb_lock_wait_timeout = 5; としておくと 5 秒でエラーになって戻る（既定は 50 秒）

-- [A1] セッションA: 作業用テーブルを作る。InnoDB の既定の分離レベルは REPEATABLE-READ
DROP TABLE IF EXISTS s10_products;
CREATE TABLE s10_products (PRIMARY KEY (id)) AS SELECT id, name, category, stock FROM products WHERE id <= 5;
SELECT @@transaction_isolation;
START TRANSACTION;
SELECT stock FROM s10_products WHERE id = 1;

-- [B1] セッションB: 在庫を 1 減らす（自動コミット）
UPDATE s10_products SET stock = stock - 1 WHERE id = 1;

-- [A2] セッションA: 普通の SELECT はスナップショット（一貫性読み取り）で 13 のまま。
--      FOR UPDATE を付けた読み取り（ロック読み取り）と UPDATE は「最新の版」を読む。PostgreSQL の Repeatable Read ならここでエラーになる
SELECT stock FROM s10_products WHERE id = 1;
SELECT stock FROM s10_products WHERE id = 1 FOR UPDATE;
UPDATE s10_products SET stock = stock - 1 WHERE id = 1;
SELECT stock FROM s10_products WHERE id = 1;
COMMIT;

-- [A3] セッションA: 「読んで → 計算して → 値を書く」更新の消失（lost update）は REPEATABLE-READ でも起きる
START TRANSACTION;
SELECT stock FROM s10_products WHERE id = 1;

-- [B2] セッションB: 同じ値を読む
START TRANSACTION;
SELECT stock FROM s10_products WHERE id = 1;

-- [A4] セッションA: 11 - 1 = 10 を書く
UPDATE s10_products SET stock = 10 WHERE id = 1;

-- [B3] セッションB: こちらも 10 を書く（ここで止まる）
UPDATE s10_products SET stock = 10 WHERE id = 1;

-- [A5] セッションA: コミットすると、セッションBの UPDATE はエラーにならずに進む（Changed: 0）
COMMIT;

-- [B4] セッションB: コミットする。2 つ売れたのに 1 つしか減っていない
COMMIT;
SELECT stock FROM s10_products WHERE id = 1;

-- [A6] セッションA: ファントムの防ぎ方：ロック読み取りは、読んだ範囲の「すき間」にもロック（ネクストキーロック）を掛ける
START TRANSACTION;
SELECT id, stock FROM s10_products WHERE id >= 4 FOR UPDATE;

-- [B5] セッションB: 範囲の外側（id=6）への INSERT も待たされる。5 秒でタイムアウトさせる（ここで止まる）
SET innodb_lock_wait_timeout = 5;
INSERT INTO s10_products VALUES (6, '商品6', '書籍', 78);

-- [C1] セッションC: 待っているトランザクションを見る
SELECT trx_id, trx_state, trx_wait_started IS NOT NULL AS waiting, trx_rows_locked, trx_query FROM information_schema.innodb_trx ORDER BY trx_started;

-- [B6] セッションB: 5秒待って、タイムアウトしたことを確認する。範囲に関係のない id=0 は入る
INSERT INTO s10_products VALUES (0, '商品0', '書籍', 1);

-- [A7] セッションA: 終わる
ROLLBACK;

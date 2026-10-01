-- S11-10 MySQL ではどうなるか（mysql クライアントで実行する）
-- 【2〜4セッション】ターミナルを開き、どれも docker compose exec lab mysql --skip-ssl -h mysql -ulab shopdb で入る。
-- 見出しごとに、書かれた側のセッションに貼る（source で一度に流さない）。
-- 途中で止まるセッションは、セッションAの COMMIT で進む。待つ上限は、行ロックが innodb_lock_wait_timeout（既定 50 秒）、
-- テーブルのメタデータロックが lock_wait_timeout（既定 31536000 秒 = 1 年）

-- [A1] セッションA: 作業用テーブルを作り、商品1の在庫を減らす
DROP TABLE IF EXISTS s11_products;
CREATE TABLE s11_products (PRIMARY KEY (id)) AS SELECT * FROM products;
START TRANSACTION;
UPDATE s11_products SET stock = stock - 1 WHERE id = 1;

-- [B1] セッションB: 商品2を減らす
START TRANSACTION;
UPDATE s11_products SET stock = stock - 1 WHERE id = 2;

-- [A2] セッションA: 商品2を減らそうとする（ここで止まる）
UPDATE s11_products SET stock = stock - 1 WHERE id = 2;

-- [B2] セッションB: 商品1を減らそうとする。InnoDB は待ちの輪ができた瞬間に検出し、片方を取り消す（待ち時間なし）
UPDATE s11_products SET stock = stock - 1 WHERE id = 1;

-- [A3] セッションA: A の UPDATE は進んでいる。コミットする
COMMIT;

-- [A4] セッションA: DDL のメタデータロック（MDL）の行列。集計のトランザクションを開いたままにする
START TRANSACTION;
SELECT COUNT(*) FROM s11_products;

-- [B3] セッションB: 列を追加しようとする（ここで止まる）
ALTER TABLE s11_products ADD COLUMN note TEXT;

-- [C1] セッションC: ただの SELECT も B の後ろで待たされる（ここで止まる）
SELECT COUNT(*) FROM s11_products;

-- [D1] セッションD: 待っている理由（State）が Waiting for table metadata lock
SELECT id, command, time, state, info FROM information_schema.processlist WHERE db = DATABASE() AND id <> CONNECTION_ID() ORDER BY id;

-- [A5] セッションA: 集計を終えると B → C の順に進む
COMMIT;

-- [A6] セッションA: もう一度、集計のトランザクションを開いたままにする
START TRANSACTION;
SELECT COUNT(*) FROM s11_products;

-- [B4] セッションB: lock_wait_timeout を 2 秒にした DDL は、2 秒であきらめる
SET SESSION lock_wait_timeout = 2;
ALTER TABLE s11_products ADD COLUMN note2 TEXT;

-- [A7] セッションA: 終わる
COMMIT;

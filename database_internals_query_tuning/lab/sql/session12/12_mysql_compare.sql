-- S12-12 MySQL ではどうなるか（mysql クライアントで実行する）
-- 【2セッション】ターミナルを開き、どちらも docker compose exec lab mysql --skip-ssl -h mysql -ulab shopdb で入る。
-- 見出しごとに、書かれた側のセッションに貼る。どこでも止まらない。
-- InnoDB は古い版を UNDO ログに持つ（テーブルの中に古い版を残さない）。UNDO は purge スレッドが後から消す
-- メモリを節約するため、作業用コピーは orders の先頭 20 万行にする

-- [A1] セッションA: 作業用コピーを作り、表領域ファイルの大きさを見る
DROP TABLE IF EXISTS s12_orders;
CREATE TABLE s12_orders (PRIMARY KEY (id)) AS SELECT * FROM orders WHERE id <= 200000;
SELECT SUBSTRING_INDEX(name, '/', -1) AS table_name, file_size, allocated_size FROM information_schema.innodb_tablespaces WHERE name = CONCAT(DATABASE(), '/s12_orders');

-- [A2] セッションA: 値を変えない UPDATE は、InnoDB では行を書き換えない（Changed: 0）
UPDATE s12_orders SET status = status;

-- [A3] セッションA: 全件の値を変える UPDATE。表領域ファイルは大きくならない（その場で書き換え、古い値は UNDO へ）
UPDATE s12_orders SET ordered_at = ordered_at + INTERVAL 1 SECOND;
SELECT SUBSTRING_INDEX(name, '/', -1) AS table_name, file_size, allocated_size FROM information_schema.innodb_tablespaces WHERE name = CONCAT(DATABASE(), '/s12_orders');

-- [A4] セッションA: 1 行ずつ 2000 回更新するプロシージャを作る（自動コミットなので 2000 個のトランザクションになる）。
--      本体に ; を含むので、DELIMITER で文の区切りを一時的に // に変える
DROP PROCEDURE IF EXISTS s12_many_updates;
DELIMITER //
CREATE PROCEDURE s12_many_updates(n INT) BEGIN DECLARE i INT DEFAULT 0; WHILE i < n DO UPDATE s12_orders SET customer_id = customer_id + 1 WHERE id = i + 1; SET i = i + 1; END WHILE; END //
DELIMITER ;

-- [B1] セッションB: 長いトランザクションを開いたままにする（一貫性読み取りのスナップショットを持ち続ける）
START TRANSACTION WITH CONSISTENT SNAPSHOT;
SELECT COUNT(*) FROM s12_orders;

-- [A5] セッションA: 2000 回の更新の前後で、purge されずに残っている UNDO の数（history list length）を見る
SELECT count AS history_list_length FROM information_schema.innodb_metrics WHERE name = 'trx_rseg_history_len';
CALL s12_many_updates(2000);
SELECT count AS history_list_length FROM information_schema.innodb_metrics WHERE name = 'trx_rseg_history_len';

-- [A6] セッションA: 5秒待ってもう一度見る。B のスナップショットが古い版を必要とするので、purge できず減らない
SELECT count AS history_list_length FROM information_schema.innodb_metrics WHERE name = 'trx_rseg_history_len';

-- [B2] セッションB: トランザクションを閉じる
COMMIT;

-- [A7] セッションA: 15秒待ってもう一度見る。purge が進んで減る（purge はバックグラウンドで少し遅れて走る）
SELECT count AS history_list_length FROM information_schema.innodb_metrics WHERE name = 'trx_rseg_history_len';

-- [A8] セッションA: まだ減っていなければ、30秒待ってもう一度見る。後片付けをする
SELECT count AS history_list_length FROM information_schema.innodb_metrics WHERE name = 'trx_rseg_history_len';
DROP PROCEDURE s12_many_updates;

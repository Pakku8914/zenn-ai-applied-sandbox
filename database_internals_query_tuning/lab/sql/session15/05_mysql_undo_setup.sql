-- S15-05 MySQL：UNDO と purge を観察する準備（1つ目の端末で実行する）
-- docker compose exec -T lab mysql --skip-ssl -h mysql -ulab shopdb -t < sql/session15/05_mysql_undo_setup.sql

-- (1) 耐久性と版管理に関わる設定（PostgreSQL の設定との対応は本文の表を参照）
SELECT @@innodb_flush_log_at_trx_commit AS flush_log_at_commit,
       @@innodb_doublewrite AS doublewrite,
       @@innodb_redo_log_capacity AS redo_log_capacity,
       @@transaction_isolation AS isolation;

-- (2) 1000 行の作業用テーブル。id = 1 の行だけを何度も更新する
DROP TABLE IF EXISTS s15_undo;
CREATE TABLE s15_undo (id INT PRIMARY KEY, v INT NOT NULL);
INSERT INTO s15_undo SELECT id, 0 FROM orders WHERE id <= 1000;

-- (3) id = 1 を 1 行ずつ n 回更新する手続き。autocommit なので 1 回の UPDATE が 1 トランザクションになる
DROP PROCEDURE IF EXISTS s15_bump;
DELIMITER //
CREATE PROCEDURE s15_bump(n INT)
BEGIN
  DECLARE i INT DEFAULT 0;
  WHILE i < n DO
    UPDATE s15_undo SET v = v + 1 WHERE id = 1;
    SET i = i + 1;
  END WHILE;
END//
DELIMITER ;

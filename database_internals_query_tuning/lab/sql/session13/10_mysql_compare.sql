-- S13-10 MySQL ではどうなるか（mysql クライアントで実行する：docker compose exec lab mysql --skip-ssl -h mysql -ulab shopdb）
-- source sql/session13/10_mysql_compare.sql でも実行できる。サーバーの設定（SET GLOBAL）は変えない。表示するだけ
-- (1) 耐久性に関わる設定：InnoDB の REDO ログ（PostgreSQL の WAL に当たる）と二重書き込みバッファ（full page writes に当たる）
SHOW VARIABLES WHERE Variable_name IN ('innodb_flush_log_at_trx_commit', 'sync_binlog', 'log_bin',
  'innodb_doublewrite', 'innodb_redo_log_capacity', 'innodb_page_size');

-- (2) REDO ログの位置（PostgreSQL の insert_lsn / flush_lsn / チェックポイントの位置に当たる）
SHOW GLOBAL STATUS WHERE Variable_name IN ('Innodb_redo_log_current_lsn', 'Innodb_redo_log_flushed_to_disk_lsn',
  'Innodb_redo_log_checkpoint_lsn');

-- (3) 1 万行を 1 行ずつ自動コミットで入れる場合と、1 トランザクションで入れる場合の、REDO の fsync 回数と時間
DROP TABLE IF EXISTS s13_my;
CREATE TABLE s13_my LIKE orders;
DROP PROCEDURE IF EXISTS s13_insert_rows;
DELIMITER //
CREATE PROCEDURE s13_insert_rows(n INT) BEGIN DECLARE i INT DEFAULT 1; WHILE i <= n DO INSERT INTO s13_my SELECT * FROM orders WHERE id = i; SET i = i + 1; END WHILE; END //
DELIMITER ;

-- (3a) 自動コミット：プロシージャの中でも 1 文ごとにコミットされる
SELECT VARIABLE_VALUE INTO @fs0 FROM performance_schema.global_status WHERE VARIABLE_NAME = 'Innodb_os_log_fsyncs';
SELECT VARIABLE_VALUE INTO @lsn0 FROM performance_schema.global_status WHERE VARIABLE_NAME = 'Innodb_redo_log_current_lsn';
SET @t0 = NOW(6);
CALL s13_insert_rows(10000);
SELECT '(3a) 自動コミット' AS run, TIMESTAMPDIFF(MICROSECOND, @t0, NOW(6)) DIV 1000 AS elapsed_ms,
  (SELECT VARIABLE_VALUE FROM performance_schema.global_status WHERE VARIABLE_NAME = 'Innodb_os_log_fsyncs') - @fs0 AS redo_fsyncs,
  (SELECT VARIABLE_VALUE FROM performance_schema.global_status WHERE VARIABLE_NAME = 'Innodb_redo_log_current_lsn') - @lsn0 AS redo_bytes;

-- (3b) 1 トランザクション
TRUNCATE s13_my;
SELECT VARIABLE_VALUE INTO @fs0 FROM performance_schema.global_status WHERE VARIABLE_NAME = 'Innodb_os_log_fsyncs';
SELECT VARIABLE_VALUE INTO @lsn0 FROM performance_schema.global_status WHERE VARIABLE_NAME = 'Innodb_redo_log_current_lsn';
SET @t0 = NOW(6);
START TRANSACTION;
CALL s13_insert_rows(10000);
COMMIT;
SELECT '(3b) 1 トランザクション' AS run, TIMESTAMPDIFF(MICROSECOND, @t0, NOW(6)) DIV 1000 AS elapsed_ms,
  (SELECT VARIABLE_VALUE FROM performance_schema.global_status WHERE VARIABLE_NAME = 'Innodb_os_log_fsyncs') - @fs0 AS redo_fsyncs,
  (SELECT VARIABLE_VALUE FROM performance_schema.global_status WHERE VARIABLE_NAME = 'Innodb_redo_log_current_lsn') - @lsn0 AS redo_bytes;

-- (4) 二重書き込みバッファの累計：ページをデータファイルへ書く前に、まず別の領域へまとめて書いた回数とページ数
SHOW GLOBAL STATUS LIKE 'Innodb_dblwr%';

-- 後片付け
DROP PROCEDURE s13_insert_rows;
DROP TABLE s13_my;

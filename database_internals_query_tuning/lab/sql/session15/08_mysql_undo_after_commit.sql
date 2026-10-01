-- S15-08 MySQL：A が COMMIT した後、purge が undo を回収する（どちらの端末でもよい）
-- docker compose exec -T lab mysql --skip-ssl -h mysql -ulab shopdb -t < sql/session15/08_mysql_undo_after_commit.sql
SELECT SLEEP(5) AS wait_for_purge;
SELECT name, count FROM information_schema.innodb_metrics WHERE name = 'trx_rseg_history_len';
DROP PROCEDURE s15_bump;

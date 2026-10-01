-- S15-06 MySQL セッション A：一貫性スナップショットを持ったまま待つ（1つ目の端末）
-- docker compose exec -T lab mysql --skip-ssl -h mysql -ulab shopdb -t < sql/session15/06_mysql_undo_session_a.sql
-- SLEEP の 40 秒のあいだに、2つ目の端末で 07_mysql_undo_session_b.sql を実行する。
-- 途中でやめるときは Ctrl+C（接続が切れるとトランザクションは ROLLBACK される）

START TRANSACTION WITH CONSISTENT SNAPSHOT;
SELECT SUM(v) FROM s15_undo;
EXPLAIN ANALYZE SELECT SUM(v) FROM s15_undo\G

SELECT SLEEP(40) AS waiting_for_session_b;

-- B が id = 1 を 5000 回更新した後でも、A のスナップショットでは合計 0 のまま（undo から古い版を組み立てる）
SELECT SUM(v) FROM s15_undo;
EXPLAIN ANALYZE SELECT SUM(v) FROM s15_undo\G
COMMIT;

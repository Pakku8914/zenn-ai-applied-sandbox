-- S15-07 MySQL セッション B：A がスナップショットを持っている間に更新する（2つ目の端末）
-- docker compose exec -T lab mysql --skip-ssl -h mysql -ulab shopdb -t < sql/session15/07_mysql_undo_session_b.sql

-- (1) History list length（purge されずに残っている、コミット済みトランザクションの undo ログの数）。
--     サーバー全体の値なので、他の接続の更新でも増える
SELECT name, count FROM information_schema.innodb_metrics WHERE name = 'trx_rseg_history_len';

-- (2) 5000 回の更新（5000 トランザクション）
CALL s15_bump(5000);
SELECT name, count FROM information_schema.innodb_metrics WHERE name = 'trx_rseg_history_len';

-- (3) 新しい読み手は、その場で書き換わった最新の版を読むだけ
SELECT SUM(v) FROM s15_undo;
EXPLAIN ANALYZE SELECT SUM(v) FROM s15_undo\G

-- (4) 古いスナップショットを持ち続けているトランザクションを探す（この DB に接続しているものだけ）
SELECT t.trx_state, t.trx_isolation_level, TIMESTAMPDIFF(SECOND, t.trx_started, NOW()) AS age_sec,
       p.command, p.info
FROM information_schema.innodb_trx t
JOIN information_schema.processlist p ON p.id = t.trx_mysql_thread_id
WHERE p.db = DATABASE();

-- (5) SHOW ENGINE INNODB STATUS の TRANSACTIONS 節にも「History list length」が出る（長いので該当箇所を探して読む）
SHOW ENGINE INNODB STATUS\G

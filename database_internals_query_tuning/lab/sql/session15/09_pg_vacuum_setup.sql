-- S15-09 PostgreSQL：同じ実験を PostgreSQL で行う準備（S10・S12 の復習）
-- 自動 VACUUM が途中で動かないように、この作業用テーブルだけ止めておく
DROP TABLE IF EXISTS s15_mvcc;
CREATE TABLE s15_mvcc (id integer PRIMARY KEY, v integer NOT NULL) WITH (autovacuum_enabled = off);
INSERT INTO s15_mvcc SELECT id, 0 FROM orders WHERE id <= 1000;
VACUUM ANALYZE s15_mvcc;
SELECT pg_relation_size('s15_mvcc') / 8192 AS pages;

-- 耐久性に関わる設定（MySQL の innodb_flush_log_at_trx_commit・innodb_doublewrite との対応は本文の表）
SELECT name, setting FROM pg_settings
WHERE name IN ('synchronous_commit', 'full_page_writes', 'max_wal_size', 'default_transaction_isolation')
ORDER BY name;

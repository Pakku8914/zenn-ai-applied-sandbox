-- S12-01 作業用コピー s12_orders（100万行）を作る
-- 1つのセッションで実行してよい: \i sql/session12/01_setup.sql（数秒で終わる）
-- 自動の VACUUM に先回りされないよう、autovacuum_enabled = off で作る（autovacuum は 10 でオンにして観察する）
-- CREATE TABLE ... AS SELECT はまとめてページを確保するため末尾に空のページが残る。orders と同じ 8197 ページにするため、
-- 空の表を作ってから id の順に INSERT する
SET client_min_messages = warning;
DROP TABLE IF EXISTS s12_orders;
RESET client_min_messages;
CREATE TABLE s12_orders (LIKE orders) WITH (autovacuum_enabled = off);
INSERT INTO s12_orders SELECT * FROM orders ORDER BY id;
ALTER TABLE s12_orders ADD PRIMARY KEY (id);
VACUUM (ANALYZE) s12_orders;
-- 出発点の大きさ
\i sql/session12/02_measure.sql

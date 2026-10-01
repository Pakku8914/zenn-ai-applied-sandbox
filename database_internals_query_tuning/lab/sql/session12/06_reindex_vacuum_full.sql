-- S12-06 大きさを戻す：REINDEX INDEX CONCURRENTLY（インデックス）と VACUUM FULL（テーブル）
-- \i sql/session12/06_reindex_vacuum_full.sql
-- 注意：VACUUM FULL はテーブルを丸ごと書き直す間 ACCESS EXCLUSIVE ロックを持ち、その間は SELECT も含めて全部止まる（08 で確かめる）

-- (1) インデックスを作り直す。CONCURRENTLY は書き込みを止めない（その代わり時間がかかり、トランザクションの中では使えない）
\timing on
REINDEX INDEX CONCURRENTLY s12_orders_pkey;
\timing off
\i sql/session12/02_measure.sql

-- (2) テーブルを詰めて書き直す
\timing on
VACUUM (FULL, VERBOSE) s12_orders;
\timing off
\i sql/session12/02_measure.sql
-- VACUUM FULL は新しいファイルに書き直す（relfilenode が変わる）
SELECT relfilenode FROM pg_class WHERE relname = 's12_orders';

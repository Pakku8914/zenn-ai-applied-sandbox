-- S12-05 VACUUM のあとにもう一度全件 UPDATE する：空きが再利用されるので、テーブルはほとんど大きくならない
-- \i sql/session12/05_update_again.sql
\timing on
UPDATE s12_orders SET status = status;
\timing off
\i sql/session12/02_measure.sql
SELECT n_tup_upd, n_tup_hot_upd, n_live_tup, n_dead_tup FROM pg_stat_user_tables WHERE relname = 's12_orders';
-- もう一度 VACUUM する
\timing on
VACUUM (VERBOSE) s12_orders;
\timing off
\i sql/session12/02_measure.sql

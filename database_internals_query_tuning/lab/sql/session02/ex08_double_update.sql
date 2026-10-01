-- 演習 S02-ex08: 同じ行を同じトランザクションで 2 回 UPDATE すると、2 回目はどこへ入るか
BEGIN;
UPDATE orders SET status = 'pending' WHERE id = 2;
SELECT ctid FROM orders WHERE id = 2;
SELECT n_tup_upd, n_tup_hot_upd FROM pg_stat_xact_user_tables WHERE relname = 'orders';

UPDATE orders SET status = 'completed' WHERE id = 2;
SELECT ctid FROM orders WHERE id = 2;
SELECT n_tup_upd, n_tup_hot_upd FROM pg_stat_xact_user_tables WHERE relname = 'orders';
ROLLBACK;

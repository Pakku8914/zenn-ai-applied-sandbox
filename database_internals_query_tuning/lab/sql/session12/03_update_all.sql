-- S12-03 100万行を全件 UPDATE する（値を変えない UPDATE でも、行ごとに新しい版が作られる）
-- \i sql/session12/03_update_all.sql（数秒で終わる）
\timing on
UPDATE s12_orders SET status = status;
\timing off
-- テーブルもインデックスもほぼ 2 倍。古い版 100 万個が不要行として残る
\i sql/session12/02_measure.sql
-- 同じページに新しい版を置けた（HOT）更新はほとんどない。ページが満杯だったため
SELECT n_tup_upd, n_tup_hot_upd, n_live_tup, n_dead_tup FROM pg_stat_user_tables WHERE relname = 's12_orders';

-- autovacuum を止めないとどうなるか。自動 ANALYZE は、前回の ANALYZE からの変更行数が次を超えると走る:
--   autovacuum_analyze_threshold（50）+ autovacuum_analyze_scale_factor（0.1）× reltuples
SHOW autovacuum_naptime;
SHOW autovacuum_analyze_threshold;
SHOW autovacuum_analyze_scale_factor;

-- 準備中に自動 ANALYZE が割り込まないよう、いったん止めて作ってから有効にする
CREATE TABLE s06_orders_auto WITH (autovacuum_enabled = false) AS SELECT * FROM orders;
-- 変更行数の集計はセッションの中にしばらく溜められてから共有メモリへ送られる。
-- 送られる前に ANALYZE すると、CTAS の 100 万行が「ANALYZE 後の変更」として数えられてしまうので、先に送らせる
SELECT pg_stat_force_next_flush();
SELECT pg_sleep(2);
ANALYZE s06_orders_auto;
ALTER TABLE s06_orders_auto SET (autovacuum_enabled = true);
SELECT 50 + 0.1 * reltuples AS 自動ANALYZEのしきい値 FROM pg_class WHERE relname = 's06_orders_auto';

INSERT INTO s06_orders_auto (id, customer_id, ordered_at, status)
SELECT id + 1000000, customer_id, ordered_at + interval '1 year', 'returned'
FROM orders WHERE id % 4 = 0;
SELECT pg_stat_force_next_flush();
SELECT now()::time(0) AS 挿入直後;

-- 2 秒おきに 15 回、自動 ANALYZE が走ったかを見る（last_autoanalyze が埋まり、n_mod_since_analyze が 0 に戻る）
SELECT now()::time(0) AS 時刻, n_mod_since_analyze, last_autoanalyze::time(0) AS 自動ANALYZE
FROM pg_stat_user_tables WHERE relname = 's06_orders_auto' \watch i=2 c=15

-- 練習（模範解答・応用）: しきい値（50 + 0.1 × reltuples = 100,050 行）を下回る変更では自動 ANALYZE が走らないことを確かめる。
CREATE TABLE s06_orders_th WITH (autovacuum_enabled = false) AS SELECT * FROM orders;
SELECT pg_stat_force_next_flush();
SELECT pg_sleep(2);
-- ANALYZE だけだと「一度も VACUUM されていない」テーブルになり、挿入行数のしきい値で自動 VACUUM が走って
-- reltuples が増え、自動 ANALYZE のしきい値まで動いてしまう。VACUUM (ANALYZE) で両方の起点をそろえる
VACUUM (ANALYZE) s06_orders_th;
ALTER TABLE s06_orders_th SET (autovacuum_enabled = true);
SELECT 50 + 0.1 * reltuples AS しきい値 FROM pg_class WHERE relname = 's06_orders_th';

-- (1) 100,000 行（しきい値未満）を追加して 30 秒待つ
INSERT INTO s06_orders_th (id, customer_id, ordered_at, status)
SELECT 1000000 + i, 1 + i % 50000, timestamptz '2026-01-01' + i * interval '1 second', 'returned'
FROM generate_series(1, 100000) AS s(i);
SELECT pg_stat_force_next_flush();
SELECT pg_sleep(30);
SELECT now()::time(0) AS 時刻, n_mod_since_analyze, last_autoanalyze::time(0) AS 自動ANALYZE
FROM pg_stat_user_tables WHERE relname = 's06_orders_th';

-- (2) さらに 100 行追加してしきい値を超えると、しばらくして走る
INSERT INTO s06_orders_th (id, customer_id, ordered_at, status)
SELECT 1100000 + i, 1, timestamptz '2026-02-01' + i * interval '1 second', 'returned'
FROM generate_series(1, 100) AS s(i);
SELECT pg_stat_force_next_flush();
SELECT now()::time(0) AS 追加直後;
SELECT now()::time(0) AS 時刻, n_mod_since_analyze, last_autoanalyze::time(0) AS 自動ANALYZE
FROM pg_stat_user_tables WHERE relname = 's06_orders_th' \watch i=3 c=10

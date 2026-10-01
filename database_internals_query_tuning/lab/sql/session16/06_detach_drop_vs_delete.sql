-- S16-06 古い月を消す：DELETE と、パーティションの DETACH / DROP の比較
-- 01〜05 の後に実行する（04 の最後で DEFAULT パーティションを消してあること）

-- (1) 比較用のパーティションなしのコピー（1月分を DELETE で消す側）
DROP TABLE IF EXISTS s16_orders_flat;
CREATE TABLE s16_orders_flat AS SELECT * FROM orders;
VACUUM ANALYZE s16_orders_flat;

-- (2) DELETE：1月の行を1行ずつ削除し、そのたびに WAL を書く。EXPLAIN (ANALYZE, WAL) で WAL の量が分かる
--     EXPLAIN ANALYZE は DELETE を本当に実行する（本番で試すときは BEGIN ... ROLLBACK で包む）
EXPLAIN (ANALYZE, WAL, COSTS OFF)
DELETE FROM s16_orders_flat
WHERE ordered_at >= '2025-01-01' AND ordered_at < '2025-02-01';

-- (3) DELETE の後には不要行が残る（VACUUM が回収するまでテーブルは小さくならない）
SELECT tuple_count, dead_tuple_count, pg_relation_size('s16_orders_flat') / 8192 AS pages
FROM pgstattuple('s16_orders_flat');

-- (4) パーティション：1月を切り離して（DETACH）から消す（DROP）。
--     CONCURRENTLY はトランザクションの中では使えない。この接続が書いた WAL の量（PostgreSQL 18 の
--     pg_stat_get_backend_wal）を前後で比べる。統計は少し遅れて反映されるので、読む前に pg_stat_force_next_flush() を呼ぶ
SELECT pg_stat_force_next_flush();
SELECT wal_records, wal_bytes FROM pg_stat_get_backend_wal(pg_backend_pid()) \gset before_
\timing on
ALTER TABLE s16_orders DETACH PARTITION s16_orders_2025_01 CONCURRENTLY;
DROP TABLE s16_orders_2025_01;
\timing off
SELECT pg_stat_force_next_flush();
SELECT wal_records - :before_wal_records AS wal_records,
       wal_bytes - :before_wal_bytes AS wal_bytes
FROM pg_stat_get_backend_wal(pg_backend_pid());

-- (5) 残った行数（1月の分だけ減っている）
SELECT (SELECT count(*) FROM s16_orders) AS partitioned_rows,
       (SELECT count(*) FROM s16_orders_flat) AS flat_rows;

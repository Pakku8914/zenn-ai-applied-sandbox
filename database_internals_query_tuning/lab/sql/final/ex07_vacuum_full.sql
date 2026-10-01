-- Final-ex07 出荷待ちキューに VACUUM FULL をかけるべきか：縮む大きさ・かかる時間・インデックスなしの Seq Scan で読むページ数
-- 12 の後に実行する（autovacuum を戻し、VACUUM 済みの状態から）
-- VACUUM FULL はテーブルを書き直す間、ACCESS EXCLUSIVE ロック（読み取りも含めて全部を止める）を取る。
-- 本番では lock_timeout を付け、他のセッションが使っていたらすぐ諦めるようにしてから実行する

-- (1) VACUUM FULL の前の大きさ
SELECT pg_relation_size('final_ship_queue') / 8192 AS pages,
       pg_size_pretty(pg_relation_size('final_ship_queue')) AS heap,
       pg_size_pretty(pg_indexes_size('final_ship_queue')) AS indexes,
       (SELECT count(*) FROM final_ship_queue) AS live_rows;

-- (2) インデックスを使わずに読んだら何ページ読むか（Q3 用のインデックスをトランザクションの中で DROP して見てから取り消す）
BEGIN;
DROP INDEX final_ship_queue_region_ordered_at_idx;
EXPLAIN (ANALYZE, BUFFERS)
SELECT order_id, customer_id, ordered_at FROM final_ship_queue
WHERE region = '東京' ORDER BY ordered_at LIMIT 50;
ROLLBACK;

-- (3) VACUUM FULL（2 秒待ってもロックが取れなければ諦める）
SET lock_timeout = '2s';
\timing on
VACUUM FULL final_ship_queue;
\timing off
RESET lock_timeout;

-- (4) 後の大きさ（インデックスも作り直される）
SELECT pg_relation_size('final_ship_queue') / 8192 AS pages,
       pg_size_pretty(pg_relation_size('final_ship_queue')) AS heap,
       pg_size_pretty(pg_indexes_size('final_ship_queue')) AS indexes,
       (SELECT count(*) FROM final_ship_queue) AS live_rows;

-- (5) もう一度、インデックスを使わずに読む
BEGIN;
DROP INDEX final_ship_queue_region_ordered_at_idx;
EXPLAIN (ANALYZE, BUFFERS)
SELECT order_id, customer_id, ordered_at FROM final_ship_queue
WHERE region = '東京' ORDER BY ordered_at LIMIT 50;
ROLLBACK;

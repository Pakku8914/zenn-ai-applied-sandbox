-- S14-04 バッファヒット率を pg_statio_* で測る。「ヒット率が低い＝ディスクが遅い」ではないことも確かめる
-- \i sql/session14/04_hit_ratio.sql
CREATE EXTENSION IF NOT EXISTS pg_buffercache;
SET max_parallel_workers_per_gather = 0;
-- このデータベースの統計の累計を 0 に戻してから、決まった処理だけを流す（他のデータベースには影響しない）
-- 統計は少し遅れて反映される。それまでの処理の未反映分がリセットの後に足されないよう、先に反映させておく
SELECT pg_stat_force_next_flush();
SELECT pg_stat_reset();
SELECT buffers_evicted FROM pg_buffercache_evict_relation('orders');
SELECT buffers_evicted FROM pg_buffercache_evict_relation('orders_pkey');
SELECT buffers_evicted FROM pg_buffercache_evict_relation('customers');

-- (A) orders の全件集計を 3 回（大きな表の Seq Scan はリングバッファを使うので、毎回ほぼ read になる）
SELECT count(*) FROM orders;
SELECT count(*) FROM orders;
SELECT count(*) FROM orders;
-- (B) customers の主キーで 1,000 行の範囲を引き、名前の長さを合計する。3 回（1 回目は read、2 回目以降は hit）
SELECT sum(length(name)) FROM customers WHERE id BETWEEN 1 AND 1000;
SELECT sum(length(name)) FROM customers WHERE id BETWEEN 1 AND 1000;
SELECT sum(length(name)) FROM customers WHERE id BETWEEN 1 AND 1000;
-- (C) orders の主キーで 1 行ずつ 3 回
SELECT status FROM orders WHERE id = 123457;
SELECT status FROM orders WHERE id = 123457;
SELECT status FROM orders WHERE id = 123457;

-- 統計は少し遅れて反映されるので、すぐ反映させてから見る
SELECT pg_stat_force_next_flush();
-- テーブル本体（heap）とそのインデックス（idx）のヒット率
SELECT relname,
       heap_blks_read, heap_blks_hit,
       round(100.0 * heap_blks_hit / nullif(heap_blks_hit + heap_blks_read, 0), 1) AS heap_hit_pct,
       idx_blks_read, idx_blks_hit,
       round(100.0 * idx_blks_hit / nullif(idx_blks_hit + idx_blks_read, 0), 1) AS idx_hit_pct
FROM pg_statio_user_tables
WHERE relname IN ('orders', 'customers')
ORDER BY relname;
-- インデックスごと
SELECT indexrelname, idx_blks_read, idx_blks_hit,
       round(100.0 * idx_blks_hit / nullif(idx_blks_hit + idx_blks_read, 0), 1) AS hit_pct
FROM pg_statio_user_indexes
WHERE relname IN ('orders', 'customers')
ORDER BY indexrelname;
-- データベース全体（カタログの読み取りも含む）
SELECT datname, blks_read, blks_hit,
       round(100.0 * blks_hit / nullif(blks_hit + blks_read, 0), 1) AS hit_pct,
       round(blk_read_time::numeric, 1) AS blk_read_time_ms
FROM pg_stat_database WHERE datname = current_database();
RESET max_parallel_workers_per_gather;

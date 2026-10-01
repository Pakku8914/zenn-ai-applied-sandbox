-- Final-06 Q3 未発送の注文の検索：読んでいるページ数と、生きている行の数が合わない
EXPLAIN (ANALYZE, BUFFERS)
SELECT order_id, customer_id, ordered_at
FROM final_ship_queue
WHERE region = '東京'
ORDER BY ordered_at
LIMIT 50;

-- (1) 生きている行は何行で、テーブルは何ページあるか。プランナが覚えている行数（reltuples）とも比べる
SELECT (SELECT count(*) FROM final_ship_queue) AS live_rows,
       pg_relation_size('final_ship_queue') / 8192 AS pages,
       pg_size_pretty(pg_relation_size('final_ship_queue')) AS size,
       reltuples::bigint AS reltuples
FROM pg_class WHERE relname = 'final_ship_queue';

-- (2) ページの中身の内訳（生きている行・不要行・空き）
SELECT table_len, tuple_count, tuple_percent, dead_tuple_count, dead_tuple_percent, free_space, free_percent
FROM pgstattuple('final_ship_queue');

-- (3) なぜ放置されたのか：テーブル単位の設定と、自動の VACUUM / ANALYZE の記録
SELECT relname, reloptions FROM pg_class WHERE relname = 'final_ship_queue';
SELECT n_live_tup, n_dead_tup, n_mod_since_analyze,
       last_vacuum, last_autovacuum, last_analyze IS NOT NULL AS analyzed_once, last_autoanalyze
FROM pg_stat_user_tables WHERE relname = 'final_ship_queue';

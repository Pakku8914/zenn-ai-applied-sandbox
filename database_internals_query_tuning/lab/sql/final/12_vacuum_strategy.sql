-- Final-12 出荷待ちキューの VACUUM 戦略：autovacuum を既定に戻し、たまった分は手で VACUUM する
-- 10 の後に実行する。VACUUM FULL をするべきかは ex07 で判断する

-- (1) 直す前（06 と同じ見方）
SELECT pg_relation_size('final_ship_queue') / 8192 AS pages, c.reltuples::bigint AS reltuples,
       s.n_live_tup, s.n_dead_tup, c.reloptions
FROM pg_class c JOIN pg_stat_user_tables s ON s.relid = c.oid
WHERE c.relname = 'final_ship_queue';

-- (2) テーブル単位の設定（autovacuum_enabled = false）を消して、既定の autovacuum に戻す
ALTER TABLE final_ship_queue RESET (autovacuum_enabled);

-- (3) たまった分は自動を待たずに手で片付ける。VERBOSE で「何ページ残ったか」を見る。ANALYZE で統計も取り直す
VACUUM (ANALYZE, VERBOSE) final_ship_queue;

-- (4) VACUUM の後。不要行は回収されたが、ページ数は変わらない
--     （生きている行は最後に積まれた 5 日分で、テーブルの末尾のページにある。VACUUM が切り詰められるのは末尾の空ページだけ）
SELECT pg_relation_size('final_ship_queue') / 8192 AS pages, c.reltuples::bigint AS reltuples,
       s.n_live_tup, s.n_dead_tup, c.reloptions
FROM pg_class c JOIN pg_stat_user_tables s ON s.relid = c.oid
WHERE c.relname = 'final_ship_queue';
SELECT table_len, tuple_count, tuple_percent, dead_tuple_count, free_space, free_percent
FROM pgstattuple('final_ship_queue');

-- (5) 次に autovacuum が走るのは不要行が何行たまったときか（既定の式：threshold + scale_factor × reltuples）
--     1 日に出荷される（DELETE される）のは約 2,620 行（06 の地域別の件数 = 1 日分）
SELECT c.reltuples::bigint AS reltuples,
       current_setting('autovacuum_vacuum_threshold') AS threshold,
       current_setting('autovacuum_vacuum_scale_factor') AS scale_factor,
       round(current_setting('autovacuum_vacuum_threshold')::int
             + current_setting('autovacuum_vacuum_scale_factor')::float8 * c.reltuples) AS vacuum_trigger,
       round(current_setting('autovacuum_analyze_threshold')::int
             + current_setting('autovacuum_analyze_scale_factor')::float8 * c.reltuples) AS analyze_trigger
FROM pg_class c WHERE c.relname = 'final_ship_queue';

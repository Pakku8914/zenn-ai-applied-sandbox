-- Final-09 もともとある orders_status_idx は使われているか（workload.py を実行した後に見る）
-- idx_scan はインデックスを探しに行った回数（インデックスを作ってからの累計。それまでの実験の分も含む）、
-- last_idx_scan は最後に使われた時刻。EXPLAIN（計画を立てるだけ）でも増えることがあるので、0 かどうかで判断する
SELECT relname AS table_name, indexrelname AS index_name, idx_scan,
       last_idx_scan IS NOT NULL AS used_ever,
       pg_size_pretty(pg_relation_size(indexrelid)) AS size
FROM pg_stat_user_indexes
WHERE relname IN ('orders', 'order_items', 'final_products', 'final_ship_queue')
ORDER BY relname, indexrelname;

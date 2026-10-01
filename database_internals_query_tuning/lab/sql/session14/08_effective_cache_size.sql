-- S14-08 effective_cache_size：メモリを確保しない「キャッシュはこれくらいあるはず」というプランナへのヒント
-- \i sql/session14/08_effective_cache_size.sql（07 の (C) と同じ「全件を ordered_at 順に」）
SET max_parallel_workers_per_gather = 0;
CREATE INDEX IF NOT EXISTS orders_ordered_at_idx ON orders (ordered_at);
SHOW effective_cache_size;
-- (1) 既定（4GB）：テーブル（64MB）は丸ごとキャッシュに載ると見なすので、インデックス順に 100 万回テーブルを引いても
--     同じページを何度もディスクから読むとは見積もらない → Index Scan
EXPLAIN SELECT * FROM orders ORDER BY ordered_at;
-- (2) 64MB（テーブルより小さい）にすると、同じページを何度も読み直すと見積もり、Index Scan が高くなる → Seq Scan ＋ Sort
SET effective_cache_size = '64MB';
EXPLAIN SELECT * FROM orders ORDER BY ordered_at;
-- 比べるため、64MB のまま Sort を禁止して Index Scan のコストを見る
SET enable_sort = off;
EXPLAIN SELECT * FROM orders ORDER BY ordered_at;
RESET enable_sort;
-- (3) 実行して比べる（この環境では (2) の方が速かった。ただし実際のキャッシュは 64MB より大きいので「正しい値」ではない）
RESET effective_cache_size;
EXPLAIN (ANALYZE, BUFFERS) SELECT * FROM orders ORDER BY ordered_at;
SET effective_cache_size = '64MB';
EXPLAIN (ANALYZE, BUFFERS) SELECT * FROM orders ORDER BY ordered_at;
-- (4) メモリを確保しない証拠：実メモリより大きな値も、その場で設定できる
SET effective_cache_size = '1TB';
SHOW effective_cache_size;
RESET effective_cache_size;
RESET max_parallel_workers_per_gather;

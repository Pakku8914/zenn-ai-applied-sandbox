-- S09-07 使われていないインデックスを見つけて消す
-- 「思いつきで貼った」インデックスがある状態で、画面のクエリを一通り流し、idx_scan（使われた回数）を見る
-- 出発点から実行する

CREATE INDEX customers_email_idx ON customers (email);
CREATE INDEX orders_customer_id_idx ON orders (customer_id);
CREATE INDEX orders_ordered_at_idx ON orders (ordered_at);
CREATE INDEX orders_status_idx ON orders (status);
CREATE INDEX orders_status_ordered_at_idx ON orders (status, ordered_at);

-- (1) 画面のクエリ（Mid01 の改善後の A・C と、日付範囲の集計 2 本）を 1 回ずつ流す
SELECT count(*) AS a_rows FROM (
  SELECT o.id FROM customers c JOIN orders o ON o.customer_id = c.id
  WHERE c.email = lower('User12345@Example.com')
) a;
SELECT count(*) AS c_rows FROM (
  SELECT id FROM orders WHERE status = 'pending' ORDER BY ordered_at DESC LIMIT 20
) c;
SELECT count(*) AS day_orders
FROM orders WHERE ordered_at >= '2025-06-01' AND ordered_at < '2025-06-02';
SELECT status, count(*) AS orders
FROM orders
WHERE ordered_at >= '2025-06-01' AND ordered_at < '2025-06-08'
GROUP BY status ORDER BY status;

-- (2) 使われた回数を見る。集計はしばらく接続の中に溜められるので、先に書き出させる
--     PostgreSQL 18 の idx_scan は「インデックスを探しに行った回数」で、スキップスキャンでは 1 回のクエリで複数回数える
SELECT pg_stat_force_next_flush();
SELECT pg_sleep(1);
SELECT s.relname AS table_name,
       s.indexrelname AS index_name,
       s.idx_scan,
       pg_size_pretty(pg_relation_size(s.indexrelid)) AS size,
       EXISTS (SELECT 1 FROM pg_constraint c WHERE c.conindid = s.indexrelid) AS backs_constraint
FROM pg_stat_user_indexes s
WHERE s.relname IN ('customers', 'orders')
  AND s.indexrelname NOT IN ('customers_pkey', 'orders_pkey')
ORDER BY s.idx_scan, s.indexrelname;

-- (3) 消してよい候補：一度も使われず、制約（主キー・一意制約・排他制約）を支えていないもの
SELECT s.indexrelname AS drop_candidate,
       pg_size_pretty(pg_relation_size(s.indexrelid)) AS size
FROM pg_stat_user_indexes s
WHERE s.relname IN ('customers', 'orders')
  AND s.idx_scan = 0
  AND NOT EXISTS (SELECT 1 FROM pg_constraint c WHERE c.conindid = s.indexrelid)
ORDER BY s.indexrelname;

-- (4) 消す。本番では DROP INDEX CONCURRENTLY を使う（テーブルへの書き込みを止めない。トランザクションの中では実行できない）
DROP INDEX CONCURRENTLY orders_status_idx;

-- (5) 使われていても、ほかのインデックスで代わりがきくものがある。
--     (status, ordered_at) を使っていたのは C と 1 週間の集計。消したら計画がどうなるかを、トランザクションの中で試してから戻す
--     注意：DROP INDEX はトランザクションが終わるまで orders を排他ロックする。本番では行わない
EXPLAIN (ANALYZE, BUFFERS)
SELECT status, count(*) AS orders
FROM orders
WHERE ordered_at >= '2025-06-01' AND ordered_at < '2025-06-08'
GROUP BY status ORDER BY status;
BEGIN;
DROP INDEX orders_status_ordered_at_idx;
EXPLAIN (ANALYZE, BUFFERS)
SELECT status, count(*) AS orders
FROM orders
WHERE ordered_at >= '2025-06-01' AND ordered_at < '2025-06-08'
GROUP BY status ORDER BY status;
ROLLBACK;

-- (6) 注意：idx_scan は「計画を立てるだけ」でも増えることがある。
--     結合の見積もりのために、プランナがインデックスで列の最小値・最大値を読みに行くため（EXPLAIN は実行しない）
SELECT pg_stat_force_next_flush();
SELECT pg_sleep(1);
SELECT indexrelname, idx_scan FROM pg_stat_user_indexes WHERE indexrelname = 'orders_customer_id_idx';
EXPLAIN (COSTS OFF)
SELECT o.id FROM customers c JOIN orders o ON o.customer_id = c.id
WHERE c.email = lower('User12345@Example.com');
SELECT pg_stat_force_next_flush();
SELECT pg_sleep(1);
SELECT indexrelname, idx_scan FROM pg_stat_user_indexes WHERE indexrelname = 'orders_customer_id_idx';

-- 後片付け
DROP INDEX customers_email_idx, orders_customer_id_idx, orders_ordered_at_idx,
           orders_status_ordered_at_idx;

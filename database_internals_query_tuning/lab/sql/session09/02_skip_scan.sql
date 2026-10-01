-- S09-02 先頭列を条件に含まないクエリ：PostgreSQL 18 のスキップスキャン
-- 出発点から実行する（01 の後片付け後でもよい）

-- (1) 先頭列の種類が少ない（status は 3 種類）複合インデックスだけがある状態で、ordered_at だけで絞る
CREATE INDEX orders_status_ordered_at_idx ON orders (status, ordered_at);

EXPLAIN (ANALYZE, BUFFERS)
SELECT count(*)
FROM orders
WHERE ordered_at >= '2025-06-01' AND ordered_at < '2025-06-02';

EXPLAIN (ANALYZE, BUFFERS)
SELECT id, ordered_at
FROM orders
WHERE ordered_at >= '2025-06-01' AND ordered_at < '2025-06-02';

-- (2) 比べるために ordered_at の単一列インデックスを足すと、そちらが選ばれる
CREATE INDEX orders_ordered_at_idx ON orders (ordered_at);
EXPLAIN (ANALYZE, BUFFERS)
SELECT count(*)
FROM orders
WHERE ordered_at >= '2025-06-01' AND ordered_at < '2025-06-02';
DROP INDEX orders_ordered_at_idx, orders_status_ordered_at_idx;

-- (3) 先頭列の種類が多い（customer_id は 5 万種類）複合インデックスでは、プランナは Seq Scan を選ぶ
CREATE INDEX orders_customer_id_ordered_at_idx ON orders (customer_id, ordered_at);
EXPLAIN (ANALYZE, BUFFERS)
SELECT count(*)
FROM orders
WHERE ordered_at >= '2025-06-01' AND ordered_at < '2025-06-02';

-- (4) Seq Scan を禁止して無理に使わせると、飛ばし読みせずにインデックスを端から端まで読む（Index Searches: 1）
SET enable_seqscan = off;
EXPLAIN (ANALYZE, BUFFERS)
SELECT count(*)
FROM orders
WHERE ordered_at >= '2025-06-01' AND ordered_at < '2025-06-02';
RESET enable_seqscan;

-- 後片付け
DROP INDEX orders_customer_id_ordered_at_idx;

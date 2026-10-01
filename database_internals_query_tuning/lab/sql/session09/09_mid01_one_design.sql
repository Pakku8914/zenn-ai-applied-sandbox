-- S09-09 Mid01 の 3 本のクエリを、1 つのインデックス設計で満たせるか
-- 出発点から実行する。Mid01 の「もともとあるインデックス」3 本から始め、A・C は Mid01 で書き換えた後の形で考える
CREATE INDEX customers_email_idx ON customers (email);
CREATE INDEX orders_customer_id_idx ON orders (customer_id);
CREATE INDEX orders_ordered_at_idx ON orders (ordered_at);

-- (1) orders に 1 本だけ置くとしたら：既存の orders のインデックスを外し、候補 1 本だけの状態で A と C を見る
DROP INDEX orders_customer_id_idx, orders_ordered_at_idx;

-- 候補 1：(customer_id, status, ordered_at)。A は引けるが、C は先頭列が customer_id なので並びに使えない
CREATE INDEX orders_cand1_idx ON orders (customer_id, status, ordered_at);
EXPLAIN (ANALYZE, BUFFERS)
SELECT o.id, o.ordered_at, o.status
FROM customers c JOIN orders o ON o.customer_id = c.id
WHERE c.email = lower('User12345@Example.com')
ORDER BY o.ordered_at DESC;
EXPLAIN (ANALYZE, BUFFERS)
SELECT id, customer_id, ordered_at FROM orders
WHERE status = 'pending' ORDER BY ordered_at DESC LIMIT 20;
DROP INDEX orders_cand1_idx;

-- 候補 2：(status, customer_id, ordered_at)。A はスキップスキャンで引ける。C は status で絞れても ordered_at の順にならない
CREATE INDEX orders_cand2_idx ON orders (status, customer_id, ordered_at);
EXPLAIN (ANALYZE, BUFFERS)
SELECT o.id, o.ordered_at, o.status
FROM customers c JOIN orders o ON o.customer_id = c.id
WHERE c.email = lower('User12345@Example.com')
ORDER BY o.ordered_at DESC;
EXPLAIN (ANALYZE, BUFFERS)
SELECT id, customer_id, ordered_at FROM orders
WHERE status = 'pending' ORDER BY ordered_at DESC LIMIT 20;
DROP INDEX orders_cand2_idx;

-- 候補 3：(status, ordered_at)。C は満たすが、A は customer_id で引けない
CREATE INDEX orders_cand3_idx ON orders (status, ordered_at);
EXPLAIN (ANALYZE, BUFFERS)
SELECT o.id, o.ordered_at, o.status
FROM customers c JOIN orders o ON o.customer_id = c.id
WHERE c.email = lower('User12345@Example.com')
ORDER BY o.ordered_at DESC;
EXPLAIN (ANALYZE, BUFFERS)
SELECT id, customer_id, ordered_at FROM orders
WHERE status = 'pending' ORDER BY ordered_at DESC LIMIT 20;
DROP INDEX orders_cand3_idx;

-- (2) 採用する設計：既存の 3 本を戻し、C 用に pending だけの部分インデックスを 1 本足す（B はインデックスではなく ANALYZE で直す）
CREATE INDEX orders_customer_id_idx ON orders (customer_id);
CREATE INDEX orders_ordered_at_idx ON orders (ordered_at);
CREATE INDEX orders_pending_ordered_at_idx ON orders (ordered_at) WHERE status = 'pending';

EXPLAIN (ANALYZE, BUFFERS)
SELECT o.id, o.ordered_at, o.status
FROM customers c JOIN orders o ON o.customer_id = c.id
WHERE c.email = lower('User12345@Example.com')
ORDER BY o.ordered_at DESC;
EXPLAIN (ANALYZE, BUFFERS)
SELECT id, customer_id, ordered_at FROM orders
WHERE status = 'pending' ORDER BY ordered_at DESC LIMIT 20;

-- (3) インデックスを足しても、書き換える前の C（row_number で 20 件）は速くならない
EXPLAIN (ANALYZE, BUFFERS)
SELECT id, customer_id, ordered_at
FROM (SELECT id, customer_id, ordered_at, row_number() OVER (ORDER BY ordered_at DESC) AS rn
      FROM orders WHERE status = 'pending') t
WHERE rn <= 20
ORDER BY rn;

-- (4) 設計全体のインデックスの大きさ（customers と orders。主キーを含む）
SELECT i.indrelid::regclass AS table_name,
       i.indexrelid::regclass AS index_name,
       pg_size_pretty(pg_relation_size(i.indexrelid)) AS size
FROM pg_index i
WHERE i.indrelid IN ('customers'::regclass, 'orders'::regclass)
ORDER BY table_name, index_name;
SELECT pg_size_pretty(sum(pg_relation_size(indexrelid))) AS total_without_pk
FROM pg_index
WHERE indrelid IN ('customers'::regclass, 'orders'::regclass)
  AND NOT indisprimary;

-- 後片付け（ex のファイルは自分で必要なインデックスを作る）
DROP INDEX customers_email_idx, orders_customer_id_idx, orders_ordered_at_idx, orders_pending_ordered_at_idx;

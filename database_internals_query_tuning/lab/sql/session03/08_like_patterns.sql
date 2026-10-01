-- セッション3-8: 前方一致・後方一致・中間一致
-- customers.email（'user' || id || '@example.com'）に B+木インデックスを作る。
-- このデータベースの照合順序は C なので、通常の B+木で前方一致の LIKE が範囲検索に変換できる
SELECT datcollate FROM pg_database WHERE datname = current_database();

CREATE INDEX customers_email_idx ON customers (email);
ANALYZE customers;

-- 前方一致: 'user123%' は「'user123' 以上 'user124' 未満」という範囲に書き換えられる（Index Cond を見る）
EXPLAIN (ANALYZE, BUFFERS) SELECT * FROM customers WHERE email LIKE 'user123%';

-- 前方一致で 1 件に絞れる場合は Index Scan
EXPLAIN (ANALYZE, BUFFERS) SELECT * FROM customers WHERE email LIKE 'user12345%';

-- 後方一致: 先頭が決まらないので範囲にできない → Seq Scan
EXPLAIN (ANALYZE, BUFFERS) SELECT * FROM customers WHERE email LIKE '%@example.com';

-- 中間一致: 同じく Seq Scan
EXPLAIN (ANALYZE, BUFFERS) SELECT * FROM customers WHERE email LIKE '%123%';

-- 1 件しか当たらない後方一致でも Seq Scan（件数ではなく「範囲にできるか」で決まる）
EXPLAIN (ANALYZE, BUFFERS) SELECT * FROM customers WHERE email LIKE '%12345@example.com';

-- Seq Scan を禁止しても、後方一致にはインデックスを使う手段がない（Disabled: true のまま Seq Scan）
SET enable_seqscan = off;
EXPLAIN (ANALYZE, BUFFERS) SELECT * FROM customers WHERE email LIKE '%12345@example.com';
RESET enable_seqscan;

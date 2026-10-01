-- S15-03 PostgreSQL：主キーの値の並びを変えて同じ 20万行を投入する
-- 04_mysql_primary_key_choice.sql と同じ値を使う（連番／ランダム順の整数／SHA-256 から作った UUID）
DROP TABLE IF EXISTS s15_pk_seq, s15_pk_rand, s15_pk_uuid;
CREATE TABLE s15_pk_seq  (id bigint PRIMARY KEY, customer_id integer NOT NULL, ordered_at timestamptz NOT NULL, status text NOT NULL);
CREATE TABLE s15_pk_rand (id bigint PRIMARY KEY, customer_id integer NOT NULL, ordered_at timestamptz NOT NULL, status text NOT NULL);
CREATE TABLE s15_pk_uuid (id uuid   PRIMARY KEY, customer_id integer NOT NULL, ordered_at timestamptz NOT NULL, status text NOT NULL);

-- (1) どれも orders の id 順に INSERT する。主キーの値だけが違う
--     rand: (id * 48271) mod (2^31 - 1)。重複しない、並びがランダムな整数（乱数を使わないので毎回同じ値）
--     uuid: id を SHA-256 にかけた先頭 16 バイト（UUID v4 のように並びがランダムな 16 バイトの値）
-- 1回の INSERT を5万行ずつに分ける（大きなトランザクションを避ける）
\timing on
INSERT INTO s15_pk_seq SELECT id, customer_id, ordered_at, status FROM orders WHERE id BETWEEN 1 AND 50000 ORDER BY id;
INSERT INTO s15_pk_seq SELECT id, customer_id, ordered_at, status FROM orders WHERE id BETWEEN 50001 AND 100000 ORDER BY id;
INSERT INTO s15_pk_seq SELECT id, customer_id, ordered_at, status FROM orders WHERE id BETWEEN 100001 AND 150000 ORDER BY id;
INSERT INTO s15_pk_seq SELECT id, customer_id, ordered_at, status FROM orders WHERE id BETWEEN 150001 AND 200000 ORDER BY id;
INSERT INTO s15_pk_rand SELECT (id * 48271) % 2147483647, customer_id, ordered_at, status FROM orders WHERE id BETWEEN 1 AND 50000 ORDER BY id;
INSERT INTO s15_pk_rand SELECT (id * 48271) % 2147483647, customer_id, ordered_at, status FROM orders WHERE id BETWEEN 50001 AND 100000 ORDER BY id;
INSERT INTO s15_pk_rand SELECT (id * 48271) % 2147483647, customer_id, ordered_at, status FROM orders WHERE id BETWEEN 100001 AND 150000 ORDER BY id;
INSERT INTO s15_pk_rand SELECT (id * 48271) % 2147483647, customer_id, ordered_at, status FROM orders WHERE id BETWEEN 150001 AND 200000 ORDER BY id;
INSERT INTO s15_pk_uuid SELECT substr(encode(sha256(id::text::bytea), 'hex'), 1, 32)::uuid, customer_id, ordered_at, status FROM orders WHERE id BETWEEN 1 AND 50000 ORDER BY id;
INSERT INTO s15_pk_uuid SELECT substr(encode(sha256(id::text::bytea), 'hex'), 1, 32)::uuid, customer_id, ordered_at, status FROM orders WHERE id BETWEEN 50001 AND 100000 ORDER BY id;
INSERT INTO s15_pk_uuid SELECT substr(encode(sha256(id::text::bytea), 'hex'), 1, 32)::uuid, customer_id, ordered_at, status FROM orders WHERE id BETWEEN 100001 AND 150000 ORDER BY id;
INSERT INTO s15_pk_uuid SELECT substr(encode(sha256(id::text::bytea), 'hex'), 1, 32)::uuid, customer_id, ordered_at, status FROM orders WHERE id BETWEEN 150001 AND 200000 ORDER BY id;
\timing off
VACUUM ANALYZE s15_pk_seq, s15_pk_rand, s15_pk_uuid;

-- (2) ヒープ（テーブル本体）と主キーのインデックスのページ数
SELECT c.relname AS table_name,
       pg_relation_size(c.oid) / 8192 AS heap_pages,
       pg_relation_size(i.indexrelid) / 8192 AS pkey_pages
FROM pg_class c JOIN pg_index i ON i.indrelid = c.oid AND i.indisprimary
WHERE c.relname IN ('s15_pk_seq', 's15_pk_rand', 's15_pk_uuid')
ORDER BY c.relname;

-- (3) 主キーの B+木のリーフの詰まり具合（avg_leaf_density ％）
SELECT 's15_pk_seq_pkey' AS index_name, leaf_pages, avg_leaf_density FROM pgstatindex('s15_pk_seq_pkey')
UNION ALL SELECT 's15_pk_rand_pkey', leaf_pages, avg_leaf_density FROM pgstatindex('s15_pk_rand_pkey')
UNION ALL SELECT 's15_pk_uuid_pkey', leaf_pages, avg_leaf_density FROM pgstatindex('s15_pk_uuid_pkey');

-- (4) ヒープの行は主キーの値に関係なく「入れた順」に積まれる（先頭ページの3行）
SELECT ctid, id FROM s15_pk_rand ORDER BY ctid LIMIT 3;

-- (5) セカンダリインデックスは行の位置（ctid・6バイト）を持つので、主キーの太さに関係なく同じ大きさになる
CREATE INDEX s15_pk_seq_ordered_at_idx  ON s15_pk_seq  (ordered_at);
CREATE INDEX s15_pk_rand_ordered_at_idx ON s15_pk_rand (ordered_at);
CREATE INDEX s15_pk_uuid_ordered_at_idx ON s15_pk_uuid (ordered_at);
SELECT relname, pg_relation_size(oid) / 8192 AS pages
FROM pg_class
WHERE relname IN ('s15_pk_seq_ordered_at_idx', 's15_pk_rand_ordered_at_idx', 's15_pk_uuid_ordered_at_idx')
ORDER BY relname;

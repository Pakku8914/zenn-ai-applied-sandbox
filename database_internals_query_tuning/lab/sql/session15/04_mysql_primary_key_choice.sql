-- S15-04 MySQL（InnoDB）：主キーの値の並びを変えて同じ 20万行を投入する（03 と同じ値）
-- docker compose exec -T lab mysql --skip-ssl -h mysql -ulab shopdb -t -vvv < sql/session15/04_mysql_primary_key_choice.sql
DROP TABLE IF EXISTS s15_pk_seq, s15_pk_rand, s15_pk_uuid;
CREATE TABLE s15_pk_seq  (id BIGINT NOT NULL PRIMARY KEY, customer_id INT NOT NULL, ordered_at DATETIME NOT NULL, status VARCHAR(10) NOT NULL);
CREATE TABLE s15_pk_rand (id BIGINT NOT NULL PRIMARY KEY, customer_id INT NOT NULL, ordered_at DATETIME NOT NULL, status VARCHAR(10) NOT NULL);
CREATE TABLE s15_pk_uuid (id BINARY(16) NOT NULL PRIMARY KEY, customer_id INT NOT NULL, ordered_at DATETIME NOT NULL, status VARCHAR(10) NOT NULL);

-- (1) どれも orders の id 順に INSERT する。InnoDB では行が主キーの B+木のリーフに主キー順で入る
-- 1回の INSERT を5万行ずつに分ける（大きなトランザクションを避ける）
INSERT INTO s15_pk_seq SELECT id, customer_id, ordered_at, status FROM orders WHERE id BETWEEN 1 AND 50000 ORDER BY id;
INSERT INTO s15_pk_seq SELECT id, customer_id, ordered_at, status FROM orders WHERE id BETWEEN 50001 AND 100000 ORDER BY id;
INSERT INTO s15_pk_seq SELECT id, customer_id, ordered_at, status FROM orders WHERE id BETWEEN 100001 AND 150000 ORDER BY id;
INSERT INTO s15_pk_seq SELECT id, customer_id, ordered_at, status FROM orders WHERE id BETWEEN 150001 AND 200000 ORDER BY id;
INSERT INTO s15_pk_rand SELECT (id * 48271) % 2147483647, customer_id, ordered_at, status FROM orders WHERE id BETWEEN 1 AND 50000 ORDER BY id;
INSERT INTO s15_pk_rand SELECT (id * 48271) % 2147483647, customer_id, ordered_at, status FROM orders WHERE id BETWEEN 50001 AND 100000 ORDER BY id;
INSERT INTO s15_pk_rand SELECT (id * 48271) % 2147483647, customer_id, ordered_at, status FROM orders WHERE id BETWEEN 100001 AND 150000 ORDER BY id;
INSERT INTO s15_pk_rand SELECT (id * 48271) % 2147483647, customer_id, ordered_at, status FROM orders WHERE id BETWEEN 150001 AND 200000 ORDER BY id;
INSERT INTO s15_pk_uuid SELECT UNHEX(LEFT(SHA2(id, 256), 32)), customer_id, ordered_at, status FROM orders WHERE id BETWEEN 1 AND 50000 ORDER BY id;
INSERT INTO s15_pk_uuid SELECT UNHEX(LEFT(SHA2(id, 256), 32)), customer_id, ordered_at, status FROM orders WHERE id BETWEEN 50001 AND 100000 ORDER BY id;
INSERT INTO s15_pk_uuid SELECT UNHEX(LEFT(SHA2(id, 256), 32)), customer_id, ordered_at, status FROM orders WHERE id BETWEEN 100001 AND 150000 ORDER BY id;
INSERT INTO s15_pk_uuid SELECT UNHEX(LEFT(SHA2(id, 256), 32)), customer_id, ordered_at, status FROM orders WHERE id BETWEEN 150001 AND 200000 ORDER BY id;

-- (2) テーブルの大きさ。information_schema.tables の値は既定で 24 時間キャッシュされるので、このセッションだけ無効にする
SET SESSION information_schema_stats_expiry = 0;
ANALYZE TABLE s15_pk_seq, s15_pk_rand, s15_pk_uuid;
SELECT table_name, data_length, data_length / 16384 AS data_pages
FROM information_schema.tables
WHERE table_schema = DATABASE() AND table_name LIKE 's15\_pk\_%'
ORDER BY table_name;

-- (3) バッファプールに載っているページの詰まり具合（ページ内のデータの大きさ ÷ 16KB）。
--     information_schema.innodb_buffer_page はバッファプール全体をなめるので、本番では実行しない
SELECT table_name, index_name, COUNT(*) AS pages, SUM(number_records) AS records,
       ROUND(AVG(data_size) / 16384 * 100, 1) AS fill_pct
FROM information_schema.innodb_buffer_page
WHERE table_name LIKE CONCAT('`', DATABASE(), '`.`s15\_pk\_%')
GROUP BY table_name, index_name
ORDER BY table_name, index_name;

-- (4) セカンダリインデックスは主キーの値を持つので、主キーが太いとセカンダリインデックスも太る
CREATE INDEX s15_pk_seq_ordered_at_idx  ON s15_pk_seq  (ordered_at);
CREATE INDEX s15_pk_rand_ordered_at_idx ON s15_pk_rand (ordered_at);
CREATE INDEX s15_pk_uuid_ordered_at_idx ON s15_pk_uuid (ordered_at);
ANALYZE TABLE s15_pk_seq, s15_pk_rand, s15_pk_uuid;
SELECT table_name, index_length, index_length / 16384 AS index_pages
FROM information_schema.tables
WHERE table_schema = DATABASE() AND table_name LIKE 's15\_pk\_%'
ORDER BY table_name;

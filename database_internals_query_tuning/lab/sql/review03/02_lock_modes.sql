-- R03-02 操作ごとに取るロックの一覧（本番の営業時間中に流してよいかを判断する材料）
-- 1つのセッションで上から順に実行してよい: \i sql/review03/02_lock_modes.sql（01 の後。10 秒ほど）
-- それぞれトランザクションの中で実行して pg_locks を見たあと ROLLBACK する（テーブルは変わらない）
-- VACUUM・CREATE INDEX CONCURRENTLY・REINDEX CONCURRENTLY・VACUUM FULL はトランザクションの中では実行できない（最後に確かめる）

-- 自分のセッションが持っているテーブルのロックを見るビュー（一時ビュー。接続を切ると消える）
CREATE OR REPLACE TEMP VIEW my_locks AS
SELECT relation::regclass::text AS rel, mode
FROM pg_locks
WHERE pid = pg_backend_pid() AND locktype = 'relation'
  AND (relation::regclass::text LIKE 'r03%' OR relation = 'customers'::regclass)
ORDER BY relation::regclass::text, mode;

-- (1) SELECT
BEGIN; SELECT count(*) FROM r03_orders WHERE id <= 10; SELECT * FROM my_locks; ROLLBACK;
-- (2) SELECT ... FOR UPDATE
BEGIN; SELECT id FROM r03_orders WHERE id = 1 FOR UPDATE; SELECT * FROM my_locks; ROLLBACK;
-- (3) UPDATE
BEGIN; UPDATE r03_orders SET status = status WHERE id = 1; SELECT * FROM my_locks; ROLLBACK;
-- (4) CREATE INDEX
BEGIN; CREATE INDEX r03_orders_customer_idx ON r03_orders (customer_id); SELECT * FROM my_locks; ROLLBACK;
-- (5) ANALYZE
BEGIN; ANALYZE r03_orders; SELECT * FROM my_locks; ROLLBACK;
-- (6) CREATE STATISTICS（拡張統計）
BEGIN; CREATE STATISTICS r03_orders_stats (dependencies) ON customer_id, ordered_at FROM r03_orders; SELECT * FROM my_locks; ROLLBACK;
-- (7) ALTER TABLE ... ADD COLUMN（書き換えなしで一瞬で終わる操作でも ACCESS EXCLUSIVE）
BEGIN; ALTER TABLE r03_orders ADD COLUMN note text; SELECT * FROM my_locks; ROLLBACK;
-- (8) ALTER TABLE ... ALTER COLUMN ... TYPE（テーブルを書き換える）
BEGIN; ALTER TABLE r03_orders ALTER COLUMN customer_id TYPE bigint; SELECT * FROM my_locks; ROLLBACK;
-- (9) 外部キーの追加（両方のテーブルに SHARE ROW EXCLUSIVE。既存の行を全部検査する）
BEGIN; ALTER TABLE r03_orders ADD CONSTRAINT r03_orders_customer_fk FOREIGN KEY (customer_id) REFERENCES customers (id); SELECT * FROM my_locks; ROLLBACK;
-- (10) 検査を後回しにした外部キー（NOT VALID）と、その検証（VALIDATE CONSTRAINT）
BEGIN; ALTER TABLE r03_orders ADD CONSTRAINT r03_orders_customer_fk FOREIGN KEY (customer_id) REFERENCES customers (id) NOT VALID; SELECT * FROM my_locks; ROLLBACK;
ALTER TABLE r03_orders ADD CONSTRAINT r03_orders_customer_fk FOREIGN KEY (customer_id) REFERENCES customers (id) NOT VALID;
BEGIN; ALTER TABLE r03_orders VALIDATE CONSTRAINT r03_orders_customer_fk; SELECT * FROM my_locks; ROLLBACK;
ALTER TABLE r03_orders DROP CONSTRAINT r03_orders_customer_fk;
-- (11) REINDEX（CONCURRENTLY なし）
BEGIN; REINDEX INDEX r03_orders_pkey; SELECT * FROM my_locks; ROLLBACK;
-- (12) TRUNCATE（ROLLBACK するので行は消えない）
BEGIN; TRUNCATE r03_orders; SELECT * FROM my_locks; ROLLBACK;
-- (13) トランザクションの中では実行できない操作
BEGIN; CREATE INDEX CONCURRENTLY r03_orders_customer_idx ON r03_orders (customer_id); ROLLBACK;
BEGIN; VACUUM r03_orders; ROLLBACK;

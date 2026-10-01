-- S11-05 待機の連鎖：C は B を待ち、B は A を待つ。根元（A）を終わらせると順にほどける
-- 【4セッション】A・B・C が当事者、D が観察役。見出しごとに、書かれた側に貼る（\i で一度に流さない）。
-- 途中で B と C が止まる。解除：A で COMMIT;（B が進む）→ B で COMMIT;（C が進む）。どこかで ROLLBACK; しても同じようにほどける。

-- [A1] セッションA: 作業用テーブルを作り直し、商品1を更新したままにする
\i sql/session11/00_setup.sql
BEGIN;
UPDATE s11_products SET stock = stock - 1 WHERE id = 1;

-- [B1] セッションB: 商品2を更新してから商品1を更新しようとする（ここで止まる。A を待つ）
BEGIN;
UPDATE s11_products SET stock = stock - 1 WHERE id = 2;
UPDATE s11_products SET stock = stock - 1 WHERE id = 1;

-- [C1] セッションC: 商品2を更新しようとする（ここで止まる。B を待つ）
BEGIN;
UPDATE s11_products SET stock = stock - 1 WHERE id = 2;

-- [D1] セッションD: 誰が誰を待っているか。blocked_by が空で、他の誰かの blocked_by に出てくる pid が根元
SELECT pid, pg_blocking_pids(pid) AS blocked_by, state, wait_event_type, wait_event, left(query, 55) AS query
FROM pg_stat_activity
WHERE datname = current_database() AND backend_type = 'client backend' AND pid <> pg_backend_pid()
ORDER BY backend_start;
-- ロックの一覧（行ロックの待ちは「相手のトランザクション番号（transactionid）のロック」を待つ形で現れる）
SELECT l.pid, l.locktype, l.transactionid AS xid, l.mode, l.granted
FROM pg_locks AS l
JOIN pg_stat_activity AS a USING (pid)
WHERE a.datname = current_database() AND a.backend_type = 'client backend' AND l.pid <> pg_backend_pid()
  AND l.locktype IN ('transactionid', 'tuple')
ORDER BY a.backend_start, l.granted DESC;

-- [A2] セッションA: 根元がコミットすると B が進む。C はまだ B を待っている
COMMIT;

-- [D2] セッションD: 連鎖が1段短くなった
SELECT pid, pg_blocking_pids(pid) AS blocked_by, state, wait_event_type, wait_event, left(query, 55) AS query
FROM pg_stat_activity
WHERE datname = current_database() AND backend_type = 'client backend' AND pid <> pg_backend_pid()
ORDER BY backend_start;

-- [B2] セッションB: コミットすると C が進む
COMMIT;

-- [C2] セッションC: コミットする
COMMIT;
SELECT id, stock FROM s11_products WHERE id IN (1, 2) ORDER BY id;

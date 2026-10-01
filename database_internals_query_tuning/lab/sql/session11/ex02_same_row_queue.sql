-- S11 演習: 同じ行に 3 人目が並んだら、誰が誰を待つか（タプルロック）
-- 【4セッション】見出しごとに、書かれた側に貼る。B と C が止まる。解除：A で COMMIT;（B が進む）→ B で COMMIT;（C が進む）

-- [A1] セッションA: 作業用テーブルを作り直し、商品1を更新したままにする
\i sql/session11/00_setup.sql
BEGIN;
UPDATE s11_products SET stock = stock - 1 WHERE id = 1;

-- [B1] セッションB: 同じ行を更新しようとする（ここで止まる）
BEGIN;
UPDATE s11_products SET stock = stock - 1 WHERE id = 1;

-- [C1] セッションC: 3 人目も同じ行を更新しようとする（ここで止まる）
BEGIN;
UPDATE s11_products SET stock = stock - 1 WHERE id = 1;

-- [D1] セッションD: 2 人目は A のトランザクション番号を、3 人目は 2 人目が持つ「行の順番待ちの札（tuple ロック）」を待つ
SELECT pid, pg_blocking_pids(pid) AS blocked_by, wait_event_type, wait_event
FROM pg_stat_activity
WHERE datname = current_database() AND backend_type = 'client backend' AND pid <> pg_backend_pid()
ORDER BY backend_start;
SELECT l.pid, l.locktype, l.mode, l.granted
FROM pg_locks AS l JOIN pg_stat_activity AS a USING (pid)
WHERE a.datname = current_database() AND l.locktype IN ('transactionid', 'tuple') AND l.pid <> pg_backend_pid()
ORDER BY a.backend_start, l.granted DESC, l.locktype;

-- [A2] セッションA: コミットすると B が進む
COMMIT;

-- [B2] セッションB: コミットすると C が進む
COMMIT;

-- [C2] セッションC: コミットして確かめる（13 から 3 回減って 10）
COMMIT;
SELECT stock FROM s11_products WHERE id = 1;

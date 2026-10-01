-- S11-09 CREATE INDEX と CREATE INDEX CONCURRENTLY：取るロックの違い（書き込みを止めるか）
-- 【4セッション】見出しごとに、書かれた側に貼る。途中で B や C が止まる。
-- 解除：前半は A で ROLLBACK;、後半は A で COMMIT;（待っている側が順に進む）。

-- [A1] セッションA: 作業用テーブルを作り直す。トランザクションの中で CREATE INDEX し、コミットせずにロックを持ち続ける
\i sql/session11/00_setup.sql
BEGIN;
CREATE INDEX s11_products_category_idx ON s11_products (category);
SELECT relation::regclass AS rel, mode, granted FROM pg_locks
WHERE pid = pg_backend_pid() AND locktype = 'relation' ORDER BY relation::regclass::text, mode;

-- [B1] セッションB: 読むのは待たない。書き込み（UPDATE）は SHARE ロックと衝突して待つ（ここで止まる）
SELECT count(*) FROM s11_products WHERE category = '書籍';
UPDATE s11_products SET stock = stock - 1 WHERE id = 1;

-- [A2] セッションA: 取り消すと B の UPDATE が進む
ROLLBACK;

-- [A3] セッションA: 今度は、書き込み中のトランザクションを開いたままにする
BEGIN;
UPDATE s11_products SET stock = stock - 1 WHERE id = 1;

-- [C1] セッションC: CREATE INDEX CONCURRENTLY は、先に始まった書き込みトランザクションの終わりを待つ（ここで止まる）
CREATE INDEX CONCURRENTLY s11_products_category_idx ON s11_products (category);

-- [D1] セッションD: C は SHARE UPDATE EXCLUSIVE（書き込みと両立）を持ち、A の仮想トランザクション番号の終わりを待っている
SELECT l.pid, l.locktype, l.relation::regclass AS rel, l.mode, l.granted
FROM pg_locks AS l JOIN pg_stat_activity AS a USING (pid)
WHERE a.datname = current_database() AND a.backend_type = 'client backend' AND l.pid <> pg_backend_pid()
  AND (l.relation = 's11_products'::regclass OR (l.locktype = 'virtualxid' AND NOT l.granted))
ORDER BY a.backend_start, l.locktype;
SELECT pid, phase, lockers_total, lockers_done, current_locker_pid FROM pg_stat_progress_create_index;

-- [B2] セッションB: CONCURRENTLY の途中でも、別の行の UPDATE は待たずに通る
UPDATE s11_products SET stock = stock - 1 WHERE id = 2;

-- [A4] セッションA: コミットすると、C のインデックス作成が進んで終わる
COMMIT;

-- [A5] セッションA: 比べるため、書き込み中のトランザクションを開いたまま、今度は普通の CREATE INDEX を別のセッションで打つ
BEGIN;
UPDATE s11_products SET stock = stock - 1 WHERE id = 1;

-- [C2] セッションC: 普通の CREATE INDEX は SHARE ロックが要るので、A の書き込みの終わりを待つ（ここで止まる）
CREATE INDEX s11_products_name_idx ON s11_products (name);

-- [B3] セッションB: 別の行の UPDATE も、先に並んだ C の後ろで待たされる（ここで止まる）
UPDATE s11_products SET stock = stock - 1 WHERE id = 2;

-- [D2] セッションD: ロックの行列
SELECT l.pid, l.mode, l.granted, pg_blocking_pids(l.pid) AS blocked_by, left(a.query, 60) AS query
FROM pg_locks AS l JOIN pg_stat_activity AS a USING (pid)
WHERE l.locktype = 'relation' AND l.relation = 's11_products'::regclass
ORDER BY a.backend_start;

-- [A6] セッションA: コミットすると C → B の順に進む
COMMIT;

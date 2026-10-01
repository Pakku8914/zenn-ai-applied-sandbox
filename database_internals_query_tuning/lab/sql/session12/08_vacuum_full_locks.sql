-- S12-08 VACUUM FULL と REINDEX が取るロック：本番の営業時間中に実行してはいけない理由
-- 【4セッション】見出しごとに、書かれた側に貼る。B と C が止まる。解除：セッションAで COMMIT;（B → C の順に進む）。
-- 06 までを実行したあとの s12_orders を使う（07 の途中の状態でもよい）

-- [A1] セッションA: 集計のトランザクションを開いたままにする（ACCESS SHARE）
BEGIN;
SELECT count(*) FROM s12_orders;

-- [B1] セッションB: VACUUM FULL は ACCESS EXCLUSIVE を待つ（ここで止まる）
VACUUM FULL s12_orders;

-- [C1] セッションC: その後ろの普通の SELECT も待たされる（ここで止まる）
SELECT count(*) FROM s12_orders WHERE id <= 10;

-- [D1] セッションD: ロックの行列
SELECT l.pid, l.mode, l.granted, pg_blocking_pids(l.pid) AS blocked_by, left(a.query, 45) AS query
FROM pg_locks AS l JOIN pg_stat_activity AS a USING (pid)
WHERE l.locktype = 'relation' AND l.relation = 's12_orders'::regclass
ORDER BY a.backend_start;

-- [A2] セッションA: コミットすると VACUUM FULL が走り、それが終わるまで C は待ち続ける
COMMIT;

-- [A3] セッションA: REINDEX（CONCURRENTLY なし）をトランザクションの中で実行し、ロックを持ったままにする
BEGIN;
REINDEX INDEX s12_orders_pkey;
SELECT relation::regclass AS rel, mode FROM pg_locks
WHERE pid = pg_backend_pid() AND locktype = 'relation' AND relation::regclass::text LIKE 's12%' ORDER BY relation::regclass::text;

-- [B2] セッションB: 主キーで 1 行引く SELECT は、インデックスの ACCESS EXCLUSIVE を待つ（ここで止まる）
SELECT status FROM s12_orders WHERE id = 1;

-- [C2] セッションC: インデックスを使わない全件の集計も、計画を立てる段階でインデックスを開こうとして待つ（ここで止まる）
SELECT count(*) FROM s12_orders;

-- [D2] セッションD: どのロックを待っているか
SELECT l.pid, l.relation::regclass AS rel, l.mode, l.granted, left(a.query, 45) AS query
FROM pg_locks AS l JOIN pg_stat_activity AS a USING (pid)
WHERE l.locktype = 'relation' AND l.relation IN ('s12_orders'::regclass, 's12_orders_pkey'::regclass)
ORDER BY a.backend_start, l.relation::regclass::text;

-- [A4] セッションA: コミットすると B と C が進む
COMMIT;

-- [A5] セッションA: 比べるため、書き込み中のトランザクションを開いたまま REINDEX CONCURRENTLY を別のセッションで打つ
BEGIN;
UPDATE s12_orders SET status = status WHERE id = 1;

-- [B3] セッションB: REINDEX CONCURRENTLY は先に始まった書き込みの終わりを待つ（ここで止まる）
REINDEX INDEX CONCURRENTLY s12_orders_pkey;

-- [C3] セッションC: その間も、主キーで引く SELECT は待たない
SELECT status FROM s12_orders WHERE id = 2;

-- [D3] セッションD: REINDEX CONCURRENTLY が持つロック（テーブルとインデックスに SHARE UPDATE EXCLUSIVE）
SELECT l.pid, l.relation::regclass AS rel, l.mode, l.granted
FROM pg_locks AS l JOIN pg_stat_activity AS a USING (pid)
WHERE l.locktype = 'relation' AND l.relation::regclass::text LIKE 's12_orders%' AND a.backend_type = 'client backend'
ORDER BY a.backend_start, l.relation::regclass::text;
SELECT pid, phase, lockers_total, lockers_done FROM pg_stat_progress_create_index;

-- [A6] セッションA: コミットすると B の REINDEX CONCURRENTLY が進んで終わる
COMMIT;

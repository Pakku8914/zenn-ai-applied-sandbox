-- S10-10 長時間トランザクションの害：開きっぱなしのトランザクションがあると、VACUUM が古い版を回収できない
-- 【2セッション】見出しごとに、書かれた側のセッションに貼る（\i で一度に流さない）。どこでも止まらない。
-- セッションAのトランザクションは COMMIT するまで開いたまま。やめるときはセッションAで COMMIT; を実行する。
-- 自動の VACUUM（autovacuum）に先回りされないよう、作業用テーブルは autovacuum_enabled = off で作る（S12 で扱う）

-- [A1] セッションA: 1万行の作業用テーブルを作り、Repeatable Read のトランザクションを開いたままにする
DROP TABLE IF EXISTS s10_vac;
CREATE TABLE s10_vac WITH (autovacuum_enabled = off) AS
  SELECT g AS id, 0 AS v FROM generate_series(1, 10000) AS g;
VACUUM s10_vac;
BEGIN ISOLATION LEVEL REPEATABLE READ;
SELECT count(*) FROM s10_vac;

-- [B1] セッションB: 全行を更新すると古い版が 1 万個できる。VACUUM しても「dead but not yet removable」のまま残る
UPDATE s10_vac SET v = v + 1;
VACUUM (VERBOSE) s10_vac;

-- [B2] セッションB: 回収を止めている犯人を探す。backend_xmin（そのセッションが見ている最も古い番号）を持つ接続
SELECT pid, state, backend_xid, backend_xmin, age(backend_xmin) AS xmin_age,
       now() - xact_start AS xact_duration, left(query, 40) AS last_query
FROM pg_stat_activity
WHERE datname = current_database() AND pid <> pg_backend_pid() AND backend_xmin IS NOT NULL;
SELECT n_live_tup, n_dead_tup FROM pg_stat_user_tables WHERE relname = 's10_vac';

-- [A2] セッションA: トランザクションを閉じる
COMMIT;

-- [B3] セッションB: 同じ VACUUM で 1 万個が回収される
VACUUM (VERBOSE) s10_vac;
SELECT n_live_tup, n_dead_tup FROM pg_stat_user_tables WHERE relname = 's10_vac';

-- [A3] セッションA: Read Committed で読むだけのトランザクションを開いたままにする
BEGIN;
SELECT count(*) FROM s10_vac;

-- [B4] セッションB: Read Committed は文ごとにスナップショットを取り直すので、読むだけなら回収を止めない
UPDATE s10_vac SET v = v + 1;
VACUUM (VERBOSE) s10_vac;
SELECT pid, state, backend_xid, backend_xmin, left(query, 40) AS last_query
FROM pg_stat_activity
WHERE datname = current_database() AND pid <> pg_backend_pid() AND state LIKE 'idle in%';

-- [A4] セッションA: 同じトランザクションで番号を受け取る（書き込みをした状態と同じ）
SELECT pg_current_xact_id();

-- [B5] セッションB: 番号を持ったトランザクションが開いている間は、Read Committed でも回収できない
UPDATE s10_vac SET v = v + 1;
VACUUM (VERBOSE) s10_vac;
SELECT pid, state, backend_xid, backend_xmin, left(query, 40) AS last_query
FROM pg_stat_activity
WHERE datname = current_database() AND pid <> pg_backend_pid() AND state LIKE 'idle in%';

-- [A5] セッションA: トランザクションを閉じる
COMMIT;

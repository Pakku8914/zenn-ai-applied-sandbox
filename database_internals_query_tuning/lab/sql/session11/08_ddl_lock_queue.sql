-- S11-08 DDL のロック待ちの行列：ALTER TABLE が待つと、その後ろの普通の SELECT まで全部待たされる
-- 【4セッション】A が長いトランザクション、B が DDL、C が普通の SELECT、D が観察役。見出しごとに、書かれた側に貼る。
-- 途中で B と C が止まる。解除：A で COMMIT;（B → C の順に進む）。B で Ctrl+C を押しても C は進む。
-- 後半は、B に lock_timeout を付けて「待つのは 2 秒まで」にし、被害を限定する。

-- [A1] セッションA: 作業用テーブルを作り直し、集計のトランザクションを開いたままにする（ACCESS SHARE ロックを持ち続ける）
\i sql/session11/00_setup.sql
BEGIN;
SELECT count(*) FROM s11_products;

-- [B1] セッションB: 列を追加する。ACCESS EXCLUSIVE ロックが要るので A の終わりを待つ（ここで止まる）
ALTER TABLE s11_products ADD COLUMN note text;

-- [C1] セッションC: ただの SELECT も、先に並んでいる B の後ろで待たされる（ここで止まる）
SELECT count(*) FROM s11_products;

-- [D1] セッションD: テーブルのロックを見る。granted = f が待っているロック
SELECT l.pid, a.state, l.mode, l.granted, pg_blocking_pids(l.pid) AS blocked_by, left(a.query, 45) AS query
FROM pg_locks AS l
JOIN pg_stat_activity AS a USING (pid)
WHERE l.locktype = 'relation' AND l.relation = 's11_products'::regclass
ORDER BY a.backend_start;

-- [A2] セッションA: 集計を終えると、B の ALTER TABLE が進み、そのあと C の SELECT が進む
COMMIT;

-- [A3] セッションA: もう一度、集計のトランザクションを開いたままにする
BEGIN;
SELECT count(*) FROM s11_products;

-- [B2] セッションB: lock_timeout を付けた DDL。2 秒待って取れなければあきらめる
SET lock_timeout = '2s';
ALTER TABLE s11_products ADD COLUMN note2 text;

-- [C2] セッションC: B があきらめたあとは、普通の SELECT はすぐ返る
SELECT count(*) FROM s11_products;

-- [B3] セッションB: statement_timeout は「文全体の時間」の上限。ロック待ちでも、ロックと関係のない長い処理でも切れる
SET lock_timeout = 0;
SET statement_timeout = '2s';
ALTER TABLE s11_products ADD COLUMN note2 text;
SELECT pg_sleep(3);
RESET statement_timeout;
-- lock_timeout はロックの待ちにしか効かないので、pg_sleep のような長い処理は切らない
SET lock_timeout = '1s';
SELECT pg_sleep(1.5);
RESET lock_timeout;

-- [A4] セッションA: 終わる
COMMIT;

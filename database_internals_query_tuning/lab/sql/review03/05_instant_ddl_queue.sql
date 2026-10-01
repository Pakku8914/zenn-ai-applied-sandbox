-- R03-05 一瞬で終わるはずの ADD COLUMN でも、長いトランザクションの後ろで待つと全員を止める。lock_timeout とリトライで被害を限定する
-- 【4セッション】見出しごとに、書かれた側に貼る。B と C が止まる。解除：セッションAで COMMIT;（B → C の順に進む）
-- 01 の後の r03_orders を使う

-- [A1] セッションA: 夜間バッチの集計のつもりで、トランザクションを開いたままにする
BEGIN;
SELECT count(*) FROM r03_orders WHERE id <= 1000;

-- [B1] セッションB: 列の追加（書き換えなしで一瞬で終わる操作）。ACCESS EXCLUSIVE を待つ（ここで止まる）
ALTER TABLE r03_orders ADD COLUMN memo text;

-- [C1] セッションC: 画面からの 1 行の参照も、B の後ろで待たされる（ここで止まる）
SELECT status FROM r03_orders WHERE id = 1;

-- [D1] セッションD: ロックの行列
SELECT l.pid, l.mode, l.granted, pg_blocking_pids(l.pid) AS blocked_by, left(a.query, 45) AS query
FROM pg_locks AS l JOIN pg_stat_activity AS a USING (pid)
WHERE l.locktype = 'relation' AND l.relation = 'r03_orders'::regclass
ORDER BY a.backend_start;

-- [A2] セッションA: 集計を終えると、B の ALTER TABLE（一瞬）と C の SELECT が進む
COMMIT;

-- [A3] セッションA: もう一度、集計のトランザクションを開いたままにする
BEGIN;
SELECT count(*) FROM r03_orders WHERE id <= 1000;

-- [B2] セッションB: 安全な流し方。lock_timeout を短くして、取れなければすぐあきらめる
SET lock_timeout = '1s';
ALTER TABLE r03_orders ADD COLUMN memo2 text;

-- [C2] セッションC: B があきらめたので、参照は待たない
SELECT status FROM r03_orders WHERE id = 1;

-- [A4] セッションA: 集計を終える
COMMIT;

-- [B3] セッションB: 少し待ってからリトライすると、今度は一瞬で通る
ALTER TABLE r03_orders ADD COLUMN memo2 text;
RESET lock_timeout;

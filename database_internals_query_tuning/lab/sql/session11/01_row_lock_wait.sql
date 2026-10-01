-- S11-01 行ロックの待ち：同じ行を2つのトランザクションが更新すると、後の方が待つ
-- 【3セッション】ターミナルを3つ開き、どれも docker compose exec lab psql で入る。見出しごとに、書かれた側に貼る（\i で一度に流さない）。
-- 途中でセッションBが止まる。解除の方法は3つ：セッションAで COMMIT;（B は進む）/ ROLLBACK;（B は進む）/
-- セッションBで Ctrl+C（B の文だけ取り消す）。待ち時間に上限を付けたいときは、先に SET lock_timeout = '2s'; を実行しておく（後半）

-- [A1] セッションA: 作業用テーブルを作り直し、商品1の在庫を 1 減らす（まだコミットしない）
\i sql/session11/00_setup.sql
BEGIN;
SELECT pg_backend_pid();
UPDATE s11_products SET stock = stock - 1 WHERE id = 1;

-- [B1] セッションB: 同じ行を更新しようとする（ここで止まる）
SELECT pg_backend_pid();
UPDATE s11_products SET stock = stock - 1 WHERE id = 1;

-- [C1] セッションC: 誰が誰を待っているか。pg_blocking_pids() が待たせている側の pid を返す
SELECT pid, pg_blocking_pids(pid) AS blocked_by, state, wait_event_type, wait_event, left(query, 55) AS query
FROM pg_stat_activity
WHERE datname = current_database() AND backend_type = 'client backend' AND pid <> pg_backend_pid()
ORDER BY backend_start;

-- [A2] セッションA: コミットすると、セッションBの UPDATE が進む
COMMIT;

-- [B2] セッションB: 2 回減って 11
SELECT stock FROM s11_products WHERE id = 1;

-- [A3] セッションA: もう一度ロックを持ったままにする
BEGIN;
UPDATE s11_products SET stock = stock - 1 WHERE id = 1;

-- [B3] セッションB: lock_timeout を付けると、2 秒待ってエラーで戻る（ロックの待ちだけに効く上限）
SET lock_timeout = '2s';
UPDATE s11_products SET stock = stock - 1 WHERE id = 1;
RESET lock_timeout;

-- [A4] セッションA: 取り消す
ROLLBACK;

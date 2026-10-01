-- Final-05 在庫引き当ての待ちを再現する（改善前の書き方：行ロックを取ってから決済 API の応答を待つ）
-- 【3セッション】ターミナルを 3 つ開き、どれも docker compose exec lab psql で入る。見出しごとに、書かれた側に貼る（\i で一度に流さない）。
-- B1 でセッションBが止まる。解除の方法は 3 つ：セッションAで COMMIT;（または ROLLBACK;）/ セッションBで Ctrl+C（B の文だけ取り消す）/
-- あらかじめ SET lock_timeout を付けておく（後半の B3）

-- [A1] セッションA: 人気商品 777 の在庫を 10 万個に戻してから、注文Xの引き当てを始める。
--      行ロックを取り、決済 API の応答を待っている状態（まだ COMMIT しない）
UPDATE final_products SET stock = 100000 WHERE id = 777;
BEGIN;
SELECT stock FROM final_products WHERE id = 777 FOR UPDATE;

-- [B1] セッションB: 注文Yが同じ商品を引き当てようとする（ここで止まる）
BEGIN;
SELECT stock FROM final_products WHERE id = 777 FOR UPDATE;

-- [C1] セッションC: 誰が誰を待っているか。A は「idle in transaction」（何もしていないのにトランザクションを開いたまま）
SELECT pid, pg_blocking_pids(pid) AS blocked_by, state, wait_event_type, wait_event, left(query, 58) AS query
FROM pg_stat_activity
WHERE datname = current_database() AND backend_type = 'client backend' AND pid <> pg_backend_pid()
ORDER BY backend_start;

-- [A2] セッションA: 決済 API が応答したので、在庫を減らしてコミットする。ここで初めてセッションBの SELECT が進む
UPDATE final_products SET stock = stock - 1 WHERE id = 777;
COMMIT;

-- [B2] セッションB: B の SELECT は A のコミット後の値（99999）を返している。B も引き当てを終える
UPDATE final_products SET stock = stock - 1 WHERE id = 777;
COMMIT;
SELECT stock FROM final_products WHERE id = 777;

-- [A3] セッションA: もう一度、ロックを持ったまま応答を待つ
BEGIN;
SELECT stock FROM final_products WHERE id = 777 FOR UPDATE;

-- [B3] セッションB: lock_timeout を付けると、2 秒待ってエラーで戻る（待ち続けて画面が固まるのを防ぐ上限）
SET lock_timeout = '2s';
SELECT stock FROM final_products WHERE id = 777 FOR UPDATE;
RESET lock_timeout;

-- [A4] セッションA: 取り消す
ROLLBACK;

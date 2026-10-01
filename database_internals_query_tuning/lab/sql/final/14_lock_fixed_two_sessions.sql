-- Final-14 改善後の在庫引き当て：「在庫が足りれば減らす」を 1 文で行い、すぐ COMMIT する（決済 API はトランザクションの外）
-- 【2セッション（C1 だけ 3 つ目）】見出しごとに、書かれた側に貼る。前半はどこでも止まらない。
-- 後半（A2〜B3）では B2 でセッションBが止まり、A3 の COMMIT で進む（止まったままにしたくなければ、セッションAで ROLLBACK; でも進む）

-- [A1] セッションA: 人気商品 777 の在庫を 10 万個に戻してから、注文Xを引き当てる（短いトランザクション）
UPDATE final_products SET stock = 100000 WHERE id = 777;
BEGIN;
UPDATE final_products SET stock = stock - 1 WHERE id = 777 AND stock >= 1 RETURNING stock;
INSERT INTO final_ship_queue (order_id, customer_id, region, ordered_at)
SELECT nextval('final_order_id_seq'), id, region, now() FROM customers WHERE id = 12345;
COMMIT;
-- ここで決済 API を呼ぶ。トランザクションの外なので、応答を待つ間も行ロックは持っていない

-- [B1] セッションB: 注文Yの引き当ては待たずに終わる
BEGIN;
UPDATE final_products SET stock = stock - 1 WHERE id = 777 AND stock >= 1 RETURNING stock;
INSERT INTO final_ship_queue (order_id, customer_id, region, ordered_at)
SELECT nextval('final_order_id_seq'), id, region, now() FROM customers WHERE id = 23456;
COMMIT;

-- 後半：短いトランザクションでも「在庫が足りるか」の判定は正しく行われる（売り越さない）
-- [A2] セッションA: 在庫を 1 個にして、A が最後の 1 個を引き当てる（まだ COMMIT しない）
UPDATE final_products SET stock = 1 WHERE id = 777;
BEGIN;
UPDATE final_products SET stock = stock - 1 WHERE id = 777 AND stock >= 1 RETURNING stock;

-- [B2] セッションB: 同じ 1 個を引き当てようとする。同じ行なので A の COMMIT を待つ（ここで止まる）
BEGIN;
UPDATE final_products SET stock = stock - 1 WHERE id = 777 AND stock >= 1 RETURNING stock;

-- [C1] セッションC（3 つ目のターミナルがあれば）: B は A を待っている。短いトランザクションでも同じ行は順番に処理される
SELECT pid, pg_blocking_pids(pid) AS blocked_by, state, wait_event_type, wait_event, left(query, 58) AS query
FROM pg_stat_activity
WHERE datname = current_database() AND backend_type = 'client backend' AND pid <> pg_backend_pid()
ORDER BY backend_start;

-- [A3] セッションA: コミットする
COMMIT;

-- [B3] セッションB: A のコミット後の行（stock = 0）で条件を評価し直すので、0 行の更新になる（在庫切れとして扱い、取り消す）
ROLLBACK;
SELECT stock FROM final_products WHERE id = 777;
-- 在庫を 10 万個に戻しておく
UPDATE final_products SET stock = 100000 WHERE id = 777;

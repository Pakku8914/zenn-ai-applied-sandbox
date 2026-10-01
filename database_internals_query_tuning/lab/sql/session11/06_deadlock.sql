-- S11-06 デッドロックを意図的に起こす：2つの商品を逆の順に更新する
-- 【2セッション】見出しごとに、書かれた側のセッションに貼る（\i で一度に流さない）。
-- A2 でセッションAが止まる。B2 を打つと約 1 秒後（deadlock_timeout）にどちらか一方がエラーで取り消され、もう一方が進む。
-- エラーになった側は ROLLBACK; する（失敗したトランザクションは ROLLBACK しかできない）。残った側は COMMIT; する。

-- [A1] セッションA: 作業用テーブルを作り直す。注文Xの引き当て：商品1 → 商品2 の順に在庫を減らす
\i sql/session11/00_setup.sql
SHOW deadlock_timeout;
BEGIN;
SELECT pg_backend_pid(), pg_current_xact_id();
UPDATE s11_products SET stock = stock - 1 WHERE id = 1;

-- [B1] セッションB: 注文Yの引き当て：商品2 → 商品1 の順に減らす
BEGIN;
SELECT pg_backend_pid(), pg_current_xact_id();
UPDATE s11_products SET stock = stock - 1 WHERE id = 2;

-- [A2] セッションA: 商品2を減らそうとする（ここで止まる。B を待つ）
UPDATE s11_products SET stock = stock - 1 WHERE id = 2;

-- [B2] セッションB: 商品1を減らそうとする。A は B を、B は A を待つ輪ができ、1 秒後にデッドロックとして検出される
UPDATE s11_products SET stock = stock - 1 WHERE id = 1;

-- [B3] セッションB: 取り消されたトランザクションを終わらせる
ROLLBACK;

-- [A3] セッションA: A は両方の更新を終えているのでコミットする
COMMIT;
SELECT id, stock FROM s11_products WHERE id IN (1, 2) ORDER BY id;

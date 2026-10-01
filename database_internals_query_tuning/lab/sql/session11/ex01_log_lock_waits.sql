-- S11 演習: ロック待ちをサーバーログに残す（log_lock_waits）
-- 【2セッション】見出しごとに、書かれた側に貼る。B1 でセッションBが止まり、A の COMMIT で進む。
-- log_lock_waits はスーパーユーザーならセッション単位で SET できる（本番では postgresql.conf で on にするのが普通）。
-- ログは別のターミナルで docker compose logs pg --tail 20 で見る

-- [A1] セッションA: 作業用テーブルを作り直し、商品1を更新したままにする
\i sql/session11/00_setup.sql
BEGIN;
UPDATE s11_products SET stock = stock - 1 WHERE id = 1;

-- [B1] セッションB: ロック待ちが deadlock_timeout（1 秒）を超えたらログに書くよう設定してから、同じ行を更新する（ここで止まる）
SET log_lock_waits = on;
UPDATE s11_products SET stock = stock - 1 WHERE id = 1;

-- [A2] セッションA: 3秒待ってからコミットする
COMMIT;

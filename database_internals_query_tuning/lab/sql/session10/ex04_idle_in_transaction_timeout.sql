-- S10 演習: 開きっぱなしのトランザクションを自動で終わらせる（idle_in_transaction_session_timeout）
-- 1つのセッションで行う。見出しごとに貼る（A2 は 3 秒待ってから貼る）。
-- タイムアウトすると接続ごと切られる。psql は自動でつなぎ直すが、トランザクションの中身は取り消されている。

-- [A1] セッションA: このセッションだけ 2 秒に設定し、トランザクションを開いたままにする
\i sql/session10/00_setup.sql
SET idle_in_transaction_session_timeout = '2s';
BEGIN;
UPDATE s10_products SET stock = 0 WHERE id = 1;

-- [A2] セッションA: 3秒待ってから次の文を打つ。接続が切られていて、UPDATE は取り消されている
SELECT stock FROM s10_products WHERE id = 1;
SELECT stock FROM s10_products WHERE id = 1;

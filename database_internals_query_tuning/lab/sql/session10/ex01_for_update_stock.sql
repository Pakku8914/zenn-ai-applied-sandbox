-- S10 演習: Read Committed のまま「読んで → 計算して → 値を書く」を安全にする（SELECT ... FOR UPDATE）
-- 【2セッション】見出しごとに、書かれた側のセッションに貼る。途中でセッションBが止まり、セッションAの COMMIT で進む。
-- 止まったまま戻したいときは、セッションAで ROLLBACK; を実行する。

-- [A1] セッションA: 作業用テーブルを作り直し、読むときに行ロックを取る
\i sql/session10/00_setup.sql
BEGIN;
SELECT stock FROM s10_products WHERE id = 1 FOR UPDATE;

-- [B1] セッションB: 同じく FOR UPDATE で読もうとする（ここで止まる）
BEGIN;
SELECT stock FROM s10_products WHERE id = 1 FOR UPDATE;

-- [A2] セッションA: 13 - 1 = 12 を書いてコミットする。セッションBの SELECT は 12 を返す
UPDATE s10_products SET stock = 12 WHERE id = 1;
COMMIT;

-- [B2] セッションB: 12 - 1 = 11 を書いてコミットする
UPDATE s10_products SET stock = 11 WHERE id = 1;
COMMIT;
SELECT stock FROM s10_products WHERE id = 1;

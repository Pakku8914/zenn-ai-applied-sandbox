-- S10-07 Read Committed の更新：待ったあと「最新の版」に対して UPDATE をやり直す
-- 【2セッション】見出しごとに、書かれた側のセッションに貼る（\i で一度に流さない）。
-- 途中でセッションBが止まる（同じ行の更新を待つ）。セッションAの COMMIT で進む。
-- 止まったまま戻したいときは、セッションAで ROLLBACK; を実行する（セッションBはそのまま UPDATE 1 で進む）。

-- [A1] セッションA: 作業用テーブルを作り直す。アプリが「読んで → 計算して → 値を書く」形で在庫を 1 減らす
\i sql/session10/00_setup.sql
BEGIN;
SELECT stock FROM s10_products WHERE id = 1;

-- [B1] セッションB: 別の注文も同時に同じ商品を 1 つ引き当てる。読んだ値は同じ 13
BEGIN;
SELECT stock FROM s10_products WHERE id = 1;

-- [A2] セッションA: 13 - 1 = 12 を書く
UPDATE s10_products SET stock = 12 WHERE id = 1;

-- [B2] セッションB: こちらも 13 - 1 = 12 を書く（ここで止まる。セッションAの行ロックを待つ）
UPDATE s10_products SET stock = 12 WHERE id = 1;

-- [A3] セッションA: コミットすると、セッションBの UPDATE が進む
COMMIT;

-- [B3] セッションB: コミットする
COMMIT;

-- [A4] セッションA: 2 つ売れたのに在庫は 1 つしか減っていない（更新の消失 = lost update）
SELECT stock FROM s10_products WHERE id = 1;

-- [A5] セッションA: 作り直して、今度は「stock = stock - 1」と相対的に書く
\i sql/session10/00_setup.sql
BEGIN;
UPDATE s10_products SET stock = stock - 1 WHERE id = 1;

-- [B4] セッションB: 同じく相対的に 1 減らす（ここで止まる）
UPDATE s10_products SET stock = stock - 1 WHERE id = 1;

-- [A6] セッションA: コミットする。セッションBは待ったあと、コミット済みの最新版（12）に対して式を評価し直す
COMMIT;

-- [A7] セッションA: 2 つ減って 11
SELECT stock FROM s10_products WHERE id = 1;

-- S10 演習: Repeatable Read のスナップショットは BEGIN の時点ではなく「最初の文」の時点で取られる
-- 【2セッション】見出しごとに、書かれた側のセッションに貼る。どこでも止まらない。

-- [A1] セッションA: 作業用テーブルを作り直し、Repeatable Read で BEGIN だけする（まだ何も読まない）
\i sql/session10/00_setup.sql
BEGIN ISOLATION LEVEL REPEATABLE READ;

-- [B1] セッションB: 在庫を 1 減らしてコミットする
UPDATE s10_products SET stock = stock - 1 WHERE id = 1;

-- [A2] セッションA: 最初の SELECT。BEGIN のあとにコミットされた更新（12）が見える
SELECT stock FROM s10_products WHERE id = 1;

-- [B2] セッションB: もう 1 減らしてコミットする
UPDATE s10_products SET stock = stock - 1 WHERE id = 1;

-- [A3] セッションA: 今度は 12 のまま（最初の SELECT でスナップショットが決まった）
SELECT stock FROM s10_products WHERE id = 1;
COMMIT;

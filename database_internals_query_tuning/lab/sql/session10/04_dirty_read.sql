-- S10-04 ダーティリード：PostgreSQL ではどの分離レベルでも起きない
-- 【2セッション】見出しごとに、書かれた側のセッションに貼る（\i で一度に流さない）。
-- この実験はどこでも止まらない。最後にセッションAで ROLLBACK; を実行して終わる。

-- [A1] セッションA: 作業用テーブルを作り直し、id=1 の在庫を 0 にする（まだコミットしない）
\i sql/session10/00_setup.sql
BEGIN;
UPDATE s10_products SET stock = 0 WHERE id = 1;
SELECT stock FROM s10_products WHERE id = 1;

-- [B1] セッションB: 最も弱い READ UNCOMMITTED を指定しても、コミット前の値（0）は見えない
BEGIN ISOLATION LEVEL READ UNCOMMITTED;
SHOW transaction_isolation;
SELECT stock FROM s10_products WHERE id = 1;
COMMIT;

-- [A2] セッションA: 取り消す
ROLLBACK;

-- S10-08 Repeatable Read の更新の競合：同じ行を先に更新・コミットされると、後の UPDATE はエラーになる
-- 【2セッション】見出しごとに、書かれた側のセッションに貼る（\i で一度に流さない）。
-- 途中でセッションBが止まる。セッションAの COMMIT で「エラーとして」戻る（ROLLBACK なら B の UPDATE が成功する）。
-- エラーになったトランザクションは ROLLBACK してから最初からやり直す（リトライ）。

-- [A1] セッションA: 作業用テーブルを作り直し、Repeatable Read で読んでから 12 を書く
\i sql/session10/00_setup.sql
BEGIN ISOLATION LEVEL REPEATABLE READ;
SELECT stock FROM s10_products WHERE id = 1;

-- [B1] セッションB: 同じく Repeatable Read で読む（13）
BEGIN ISOLATION LEVEL REPEATABLE READ;
SELECT stock FROM s10_products WHERE id = 1;

-- [A2] セッションA: 12 を書く
UPDATE s10_products SET stock = 12 WHERE id = 1;

-- [B2] セッションB: 12 を書こうとする（ここで止まる）
UPDATE s10_products SET stock = 12 WHERE id = 1;

-- [A3] セッションA: コミットすると、セッションBの UPDATE は could not serialize access due to concurrent update で失敗する
COMMIT;

-- [B3] セッションB: 失敗したトランザクションは ROLLBACK しかできない。最初からやり直すと 12 を読み、11 を書ける
ROLLBACK;
BEGIN ISOLATION LEVEL REPEATABLE READ;
SELECT stock FROM s10_products WHERE id = 1;
UPDATE s10_products SET stock = 11 WHERE id = 1;
COMMIT;

-- [A4] セッションA: 2 つ減って 11（更新の消失は起きなかった）
SELECT stock FROM s10_products WHERE id = 1;

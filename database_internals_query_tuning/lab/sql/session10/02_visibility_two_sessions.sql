-- S10-02 読み取りは書き込みを待たない：コミット前の更新は、他のセッションには古い版で見える
-- 【2セッション】ターミナルを2つ開き、どちらも docker compose exec lab psql で入る。
-- 「-- [A1] セッションA」などの見出しごとに、書かれた側のセッションに貼る（\i で一度に流さない）。
-- この実験はどこでも止まらない。途中でやめるときはセッションAで ROLLBACK; を実行する。

-- [A1] セッションA: 作業用テーブルを作り直し、トランザクションを始めて在庫を更新する（まだコミットしない）
\i sql/session10/00_setup.sql
BEGIN;
SELECT pg_current_xact_id();
UPDATE s10_products SET stock = 0 WHERE id = 1;
SELECT xmin, xmax, ctid, * FROM s10_products WHERE id = 1;

-- [B1] セッションB: 同じ行を読む。待たされずに古い版（stock=13）が返る。xmax にはセッションAの番号が入っている
SELECT xmin, xmax, ctid, * FROM s10_products WHERE id = 1;

-- [B2] セッションB: 別の商品を追加してコミットする（番号が1つ進む）。そのあとスナップショット（xmin:xmax:実行中の番号の一覧）を見る。
--      xmin 以上 xmax 未満のうち一覧にある番号（セッションA）は「実行中」として見えない。自分がコミットした追加（id=6）は見える
INSERT INTO s10_products VALUES (6, '商品6', '書籍', 78);
SELECT pg_current_snapshot();
SELECT xmin, xmax, ctid, id, stock FROM s10_products ORDER BY id;
SELECT pg_xact_status(xmax::text::xid8) FROM s10_products WHERE id = 1;

-- [A2] セッションA: コミットする
COMMIT;

-- [B3] セッションB: 今度は新しい版（stock=0）が見える
SELECT xmin, xmax, ctid, id, stock FROM s10_products ORDER BY id;
SELECT pg_current_snapshot();

-- S10-06 ファントム：Read Committed では条件に合う行が途中で増える。PostgreSQL の Repeatable Read では増えない
-- 【2セッション】見出しごとに、書かれた側のセッションに貼る（\i で一度に流さない）。
-- この実験はどこでも止まらない（セッションBの INSERT は自動コミット）。

-- [A1] セッションA: 作業用テーブルを作り直し、Read Committed で「書籍」の商品数を数える
\i sql/session10/00_setup.sql
BEGIN;
SELECT count(*) FROM s10_products WHERE category = '書籍';

-- [B1] セッションB: 書籍の商品を 1 つ追加してコミットする
INSERT INTO s10_products VALUES (6, '商品6', '書籍', 78);

-- [A2] セッションA: 同じ条件で数え直すと 2 → 3 に増える（ファントム）
SELECT count(*) FROM s10_products WHERE category = '書籍';
COMMIT;

-- [A3] セッションA: 今度は Repeatable Read で数える
BEGIN ISOLATION LEVEL REPEATABLE READ;
SELECT count(*) FROM s10_products WHERE category = '書籍';

-- [B2] セッションB: もう 1 つ追加してコミットする
INSERT INTO s10_products VALUES (7, '商品7', '書籍', 91);

-- [A4] セッションA: 3 のまま（スナップショットにない行は見えない）。コミット後は 4
SELECT count(*) FROM s10_products WHERE category = '書籍';
COMMIT;
SELECT count(*) FROM s10_products WHERE category = '書籍';

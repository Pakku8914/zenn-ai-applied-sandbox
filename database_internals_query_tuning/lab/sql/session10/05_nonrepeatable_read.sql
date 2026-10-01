-- S10-05 反復不能読み取り：Read Committed では同じ SELECT の結果が途中で変わる。Repeatable Read では変わらない
-- 【2セッション】見出しごとに、書かれた側のセッションに貼る（\i で一度に流さない）。
-- この実験はどこでも止まらない（セッションBの UPDATE は自動コミット）。

-- [A1] セッションA: 作業用テーブルを作り直し、Read Committed（既定）で読む
\i sql/session10/00_setup.sql
BEGIN;
SHOW transaction_isolation;
SELECT stock FROM s10_products WHERE id = 1;

-- [B1] セッションB: 在庫を 1 減らしてコミットする（BEGIN なしの 1 文は自動でコミットされる）
UPDATE s10_products SET stock = stock - 1 WHERE id = 1;

-- [A2] セッションA: 同じトランザクションの中で同じ SELECT をもう一度。13 → 12 に変わる（反復不能読み取り）
SELECT stock FROM s10_products WHERE id = 1;
COMMIT;

-- [A3] セッションA: 今度は Repeatable Read で読む
BEGIN ISOLATION LEVEL REPEATABLE READ;
SELECT stock FROM s10_products WHERE id = 1;

-- [B2] セッションB: もう一度 1 減らしてコミットする
UPDATE s10_products SET stock = stock - 1 WHERE id = 1;
SELECT stock FROM s10_products WHERE id = 1;

-- [A4] セッションA: 最初の SELECT の時点のスナップショットを使い続けるので 12 のまま。コミット後の新しい文では 11 が見える
SELECT stock FROM s10_products WHERE id = 1;
COMMIT;
SELECT stock FROM s10_products WHERE id = 1;

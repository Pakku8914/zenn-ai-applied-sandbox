-- S11-02 SELECT ... FOR UPDATE / FOR SHARE / NOWAIT：読むときに行ロックを取る
-- 【2セッション】見出しごとに、書かれた側のセッションに貼る。この実験は止まらない（NOWAIT と lock_timeout ですぐ戻る）。
-- 最後にセッションAで COMMIT; を実行して終わる。

-- [A1] セッションA: 作業用テーブルを作り直し、商品1を FOR UPDATE でロックする（在庫の引き当て前の確認のつもり）
\i sql/session11/00_setup.sql
BEGIN;
SELECT id, stock FROM s11_products WHERE id = 1 FOR UPDATE;

-- [B1] セッションB: 普通の SELECT は待たずに読める（MVCC）。ロックを取る読み取りは NOWAIT を付けるとすぐエラーで戻る
SELECT id, stock FROM s11_products WHERE id = 1;
SELECT id, stock FROM s11_products WHERE id = 1 FOR UPDATE NOWAIT;
SELECT id, stock FROM s11_products WHERE id = 1 FOR SHARE NOWAIT;
SELECT id, stock FROM s11_products WHERE id = 1 FOR KEY SHARE NOWAIT;

-- [A2] セッションA: いったん終えて、今度は FOR SHARE（共有ロック）で読む
COMMIT;
BEGIN;
SELECT id, stock FROM s11_products WHERE id = 1 FOR SHARE;

-- [B2] セッションB: FOR SHARE どうしは両立する。UPDATE は FOR SHARE と衝突するので、1 秒の lock_timeout で戻す
BEGIN;
SELECT id, stock FROM s11_products WHERE id = 1 FOR SHARE NOWAIT;
SET LOCAL lock_timeout = '1s';
UPDATE s11_products SET stock = stock - 1 WHERE id = 1;
ROLLBACK;

-- [A3] セッションA: 終わる
COMMIT;

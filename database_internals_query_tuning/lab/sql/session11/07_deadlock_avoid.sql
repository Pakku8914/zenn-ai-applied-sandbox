-- S11-07 デッドロックを設計で消す：どのトランザクションも「商品 id の小さい順」にロックを取る
-- 【2セッション】見出しごとに、書かれた側のセッションに貼る。B1 でセッションBが止まるが、A の COMMIT で進む（デッドロックにはならない）。
-- 注文Y は本来「商品2 → 商品1」の順だが、先に id の昇順で FOR UPDATE を取ってから更新する

-- [A1] セッションA: 注文X（商品1・商品2）。使う行を id の昇順でまとめてロックしてから更新する
\i sql/session11/00_setup.sql
BEGIN;
SELECT id FROM s11_products WHERE id IN (1, 2) ORDER BY id FOR UPDATE;
UPDATE s11_products SET stock = stock - 1 WHERE id = 1;

-- [B1] セッションB: 注文Y（商品2・商品1）も、同じく id の昇順でロックを取ろうとする（ここで止まる。最初の商品1で待つので、何も持たずに待つ）
BEGIN;
SELECT id FROM s11_products WHERE id IN (2, 1) ORDER BY id FOR UPDATE;

-- [A2] セッションA: 残りを更新してコミットする
UPDATE s11_products SET stock = stock - 1 WHERE id = 2;
COMMIT;

-- [B2] セッションB: ロックが取れたので、本来の順（商品2 → 商品1）に更新してもデッドロックにならない
UPDATE s11_products SET stock = stock - 1 WHERE id = 2;
UPDATE s11_products SET stock = stock - 1 WHERE id = 1;
COMMIT;
SELECT id, stock FROM s11_products WHERE id IN (1, 2) ORDER BY id;

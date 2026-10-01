-- S11-03 外部キーの検査が取る行ロック（FOR KEY SHARE）：キー以外の更新とは衝突しない
-- 【2セッション】見出しごとに、書かれた側のセッションに貼る。後半でセッションBが止まり、セッションAの ROLLBACK で進む。

-- [A1] セッションA: 作業用テーブルを作り直し、商品1の在庫を更新する（キー以外の列の UPDATE = FOR NO KEY UPDATE 相当の行ロック）
\i sql/session11/00_setup.sql
BEGIN;
UPDATE s11_products SET stock = stock - 1 WHERE id = 1;

-- [B1] セッションB: 商品1を参照する注文明細を追加する。外部キーの検査は商品1に FOR KEY SHARE を取るが、上の UPDATE とは両立するので待たない
INSERT INTO s11_order_lines (product_id, quantity) VALUES (1, 2);

-- [A2] セッションA: いったんコミットし、今度は商品3を削除しようとする（削除はキーを消すので FOR UPDATE 相当の強い行ロック）
COMMIT;
BEGIN;
DELETE FROM s11_products WHERE id = 3;

-- [B2] セッションB: 商品3を参照する明細の追加は、外部キーの検査が待たされる（ここで止まる）
INSERT INTO s11_order_lines (product_id, quantity) VALUES (3, 1);

-- [A3] セッションA: 削除を取り消すと、セッションBの INSERT が進む
ROLLBACK;

-- [B3] セッションB: 明細は 2 行
SELECT * FROM s11_order_lines ORDER BY id;

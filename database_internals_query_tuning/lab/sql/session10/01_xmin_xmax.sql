-- S10-01 xmin / xmax：行の版に「作ったトランザクション」と「消したトランザクション」の番号が付く
-- 1つのセッションで上から順に実行してよい: \i sql/session10/01_xmin_xmax.sql
-- 出てくる番号（xmin・xmax・pg_current_xact_id()）は環境ごとに違う。見るのは「どの番号がどこに入るか」

\i sql/session10/00_setup.sql

-- (1) 作ったばかりの行。xmin = 作ったトランザクションの番号、xmax = 0（まだ誰も消していない）
SELECT xmin, xmax, ctid, * FROM s10_products ORDER BY id;

-- (2) トランザクションの中で id=1 の在庫を 1 減らす
BEGIN;
SELECT pg_current_xact_id();
UPDATE s10_products SET stock = stock - 1 WHERE id = 1;
-- 見える版は新しい版：xmin が自分の番号、ctid が (0,6) に変わる
SELECT xmin, xmax, ctid, * FROM s10_products WHERE id = 1;
COMMIT;

-- (3) ページの中には古い版も残っている。古い版の t_xmax と新しい版の t_xmin が同じ番号
SELECT lp, t_xmin, t_xmax, t_ctid
FROM heap_page_items(get_raw_page('s10_products', 0))
ORDER BY lp;

-- (4) 削除も「xmax を入れるだけ」。DELETE した版はページに残る（回収するのは VACUUM → S12）
BEGIN;
DELETE FROM s10_products WHERE id = 5;
SELECT pg_current_xact_id();
SELECT lp, t_xmin, t_xmax, t_ctid
FROM heap_page_items(get_raw_page('s10_products', 0))
WHERE lp = 5;
ROLLBACK;

-- (5) ROLLBACK しても t_xmax の番号は消えない。その番号のトランザクションが「取り消された」ことは
--     コミットログ（pg_xact）に記録されていて、可視性の判定のたびにそこを見る
SELECT lp, t_xmin, t_xmax, t_ctid
FROM heap_page_items(get_raw_page('s10_products', 0))
WHERE lp = 5;
SELECT t_xmax, pg_xact_status(t_xmax::text::xid8) AS xmax_status
FROM heap_page_items(get_raw_page('s10_products', 0))
WHERE lp = 5;
SELECT * FROM s10_products WHERE id = 5;

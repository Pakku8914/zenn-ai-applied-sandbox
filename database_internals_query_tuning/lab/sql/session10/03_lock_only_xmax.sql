-- S10-03 行ロックだけでも xmax が入る：更新と見分けるには t_infomask を見る
-- 1つのセッションで上から順に実行してよい: \i sql/session10/03_lock_only_xmax.sql

\i sql/session10/00_setup.sql

-- (1) id=2 を FOR UPDATE でロックする（値は変えない）
BEGIN;
SELECT pg_current_xact_id();
SELECT * FROM s10_products WHERE id = 2 FOR UPDATE;
-- xmax に自分の番号が入る。ctid は変わらない（新しい版は作られていない）
SELECT xmin, xmax, ctid, * FROM s10_products WHERE id = 2;
COMMIT;

-- (2) 比較のため id=3 を本当に更新する
UPDATE s10_products SET stock = stock - 1 WHERE id = 3;

-- (3) t_infomask を読み解く。HEAP_XMAX_LOCK_ONLY が立っていれば「ロックしただけ」で、行はまだ生きている。
--     lp=3（更新された古い版）には LOCK_ONLY がなく、t_ctid が新しい版 (0,6) を指す
SELECT lp, t_xmin, t_xmax, t_ctid, f.raw_flags
FROM heap_page_items(get_raw_page('s10_products', 0)) AS h,
     LATERAL heap_tuple_infomask_flags(h.t_infomask, h.t_infomask2) AS f
WHERE lp IN (2, 3, 6)
ORDER BY lp;

-- (4) シードした orders の行も xmax が入っている。order_items を投入したときの外部キー検査が
--     参照先の行に付けた KEY SHARE の行ロック（HEAP_XMAX_KEYSHR_LOCK + HEAP_XMAX_LOCK_ONLY）の跡
SELECT xmin, xmax, ctid, id, status FROM orders WHERE id = 1;
SELECT lp, t_xmin, t_xmax, f.raw_flags
FROM heap_page_items(get_raw_page('orders', 0)) AS h,
     LATERAL heap_tuple_infomask_flags(h.t_infomask, h.t_infomask2) AS f
WHERE lp = 1;

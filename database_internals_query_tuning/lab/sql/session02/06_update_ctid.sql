-- セッション2-6: UPDATE すると ctid が変わる（行は「書き換え」ではなく「新しい版の追加」）
-- orders の行を本当に変えないよう、トランザクションの中で実験して最後に ROLLBACK する。
-- もう一度やり直すときは、先に tools/reset.sh を実行する（ROLLBACK した版もページに残るため、2 回目は番号がずれる）

BEGIN;

-- 更新前: id=1 は 0 ページ目の 1 番
SELECT ctid, * FROM orders WHERE id = 1;

-- 更新前の lp=1。t_xmax が 0 ではないが、これはシード投入時の外部キー検査が付けた「行ロックの印」
-- （HEAP_XMAX_LOCK_ONLY）で、行が削除・更新された印ではない
SELECT lp, t_xmin, t_xmax, t_ctid, f.raw_flags
FROM heap_page_items(get_raw_page('orders', 0)) AS h,
     LATERAL heap_tuple_infomask_flags(h.t_infomask, h.t_infomask2) AS f
WHERE lp = 1;

UPDATE orders SET status = 'pending' WHERE id = 1;

-- 更新後: 同じ id=1 が別の場所にいる
SELECT ctid, * FROM orders WHERE id = 1;

-- 自分のトランザクション番号
SELECT pg_current_xact_id();

-- 古い版は 0 ページ目に残ったまま。t_xmax に更新したトランザクションの番号が入り、t_ctid が新しい版を指す
SELECT lp, lp_off, lp_len, t_xmin, t_xmax, t_ctid
FROM heap_page_items(get_raw_page('orders', 0))
WHERE lp = 1;

-- 新しい版の側（最終ページ 8196 の末尾）
SELECT lp, lp_off, lp_len, t_xmin, t_xmax, t_ctid
FROM heap_page_items(get_raw_page('orders', 8196))
WHERE lp >= 88
ORDER BY lp;

-- 0 ページ目は満杯（空き 8 バイト）なので、新しい版は空きのある別のページに置かれた。
-- 同じページに置けたときだけ HOT（Heap Only Tuple）更新になる
SELECT n_tup_upd, n_tup_hot_upd FROM pg_stat_xact_user_tables WHERE relname = 'orders';

-- 0 ページ目の先頭を物理的な順に読むと、id=1 はもういない（ヒープは順序を持たない置き場）。
-- 「ORDER BY なしの LIMIT」は先頭ページから読むとは限らないので、ctid の範囲で 0 ページ目を指定する
SELECT ctid, id FROM orders WHERE ctid < '(0,5)';

ROLLBACK;

-- ROLLBACK したので、見える行は元の位置の版に戻る
SELECT ctid, * FROM orders WHERE id = 1;

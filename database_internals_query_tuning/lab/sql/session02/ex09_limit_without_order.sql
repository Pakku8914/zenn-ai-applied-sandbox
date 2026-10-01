-- 演習 S02-ex09: ORDER BY なしの LIMIT は「先頭のページから」読むとは限らない
-- orders（8197 ページ）は shared_buffers の 1/4（256MB / 4 = 8192 ページ）より大きいので、
-- Seq Scan は「同じテーブルを直前に走査していた位置」から読み始めることがある（synchronize_seqscans）
SHOW synchronize_seqscans;
SELECT ctid, id FROM orders LIMIT 3;

-- 順序が必要なら ORDER BY を書く。物理位置で読みたいなら ctid の範囲を指定する
SELECT ctid, id FROM orders ORDER BY id LIMIT 3;
SELECT ctid, id FROM orders WHERE ctid < '(0,4)';

-- products（37 ページ）は小さいので同期スキャンの対象にならず、常に先頭ページから読む
SELECT ctid, id FROM products LIMIT 3;

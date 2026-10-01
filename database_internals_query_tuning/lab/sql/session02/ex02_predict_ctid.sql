-- 演習 S02-ex02: id=1000 の行の ctid を計算で予想してから確かめる
-- orders は 1 ページに 122 行ずつ id 順に並ぶ（最終ページを除く）
--   ページ番号 = (id - 1) / 122（整数の割り算）、ページ内の番号 = (id - 1) % 122 + 1
SELECT (1000 - 1) / 122 AS page, (1000 - 1) % 122 + 1 AS lp;

SELECT ctid, * FROM orders WHERE id = 1000;

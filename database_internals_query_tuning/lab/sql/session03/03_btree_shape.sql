-- セッション3-3: B+木の形（高さ・段ごとのページ数・1 ページのキー数）
-- bt_metap: メタページ（0 ページ目）。root = ルートのページ番号、level = ルートの段（リーフが 0）
SELECT root, level, fastroot, fastlevel FROM bt_metap('orders_ordered_at_idx');

-- 木の高さ = ルートの level + 1
SELECT level + 1 AS height FROM bt_metap('orders_ordered_at_idx');

-- 段ごとのページ数と、1 ページあたりの項目数（type: r=ルート, i=内部, l=リーフ）
-- bt_multi_page_stats(インデックス, 開始ページ, 個数) は -1 で最後まで。0 ページ目はメタページなので 1 から
SELECT btpo_level AS level, type, count(*) AS pages,
       round(avg(live_items), 1) AS avg_items, min(live_items) AS min_items, max(live_items) AS max_items
FROM bt_multi_page_stats('orders_ordered_at_idx', 1, -1)
GROUP BY btpo_level, type
ORDER BY btpo_level DESC;

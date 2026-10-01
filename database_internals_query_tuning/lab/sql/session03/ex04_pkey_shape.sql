-- 演習 S03-ex04: 主キーのインデックス orders_pkey（bigint）の形を ordered_at のインデックスと比べる
-- どちらもキーは 8 バイト。項目は「8 バイトのヘッダ + 8 バイトのキー = 16 バイト」＋行ポインタ 4 バイト
SELECT 'orders_pkey' AS idx, level + 1 AS height, pg_relation_size('orders_pkey') / 8192 AS pages
FROM bt_metap('orders_pkey')
UNION ALL
SELECT 'orders_ordered_at_idx', level + 1, pg_relation_size('orders_ordered_at_idx') / 8192
FROM bt_metap('orders_ordered_at_idx');

SELECT btpo_level AS level, type, count(*) AS pages, round(avg(live_items), 1) AS avg_items
FROM bt_multi_page_stats('orders_pkey', 1, -1)
GROUP BY btpo_level, type
ORDER BY btpo_level DESC;

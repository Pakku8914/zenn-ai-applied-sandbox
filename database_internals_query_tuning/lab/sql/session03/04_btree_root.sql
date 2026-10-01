-- セッション3-4: ルートページと内部ページのキーを読む
-- bt_page_items の data はキーの生のバイト列（16 進）。timestamptz は「2000-01-01 からのマイクロ秒」を
-- リトルエンディアンの 8 バイト整数で持つので、バイトを逆順に並べ替えて整数に戻し、日時に直して表示する。
-- ctid の前半（ページ番号）が「1 つ下の段の子ページ」を指す。
-- キーが空の項目は「-∞」（その子ページには、次の項目のキーより小さいものがすべて入る）。
-- 右端でないページでは、1 番目の項目が high key（このページに入るキーの上限）で、-∞ はその次に来る

-- ルートページの統計（type=r）
SELECT blkno, type, live_items, btpo_prev, btpo_next, btpo_level
FROM bt_page_stats('orders_ordered_at_idx', (SELECT root FROM bt_metap('orders_ordered_at_idx')));

-- ルートページの全項目
SELECT itemoffset, ctid AS downlink, itemlen,
       TIMESTAMPTZ '2000-01-01 00:00:00+00'
         + ('x' || (SELECT string_agg(b, '' ORDER BY n DESC)
                    FROM unnest(string_to_array(data, ' ')) WITH ORDINALITY AS u(b, n)))::bit(64)::bigint
           * INTERVAL '1 microsecond' AS key
FROM bt_page_items('orders_ordered_at_idx', (SELECT root FROM bt_metap('orders_ordered_at_idx')));

-- ルートの 2 番目の子（内部ページ）の先頭 5 項目。ここの ctid はリーフページを指す
SELECT blkno, type, live_items, btpo_prev, btpo_next, btpo_level
FROM bt_page_stats('orders_ordered_at_idx', 289);

SELECT itemoffset, ctid AS downlink, itemlen,
       TIMESTAMPTZ '2000-01-01 00:00:00+00'
         + ('x' || (SELECT string_agg(b, '' ORDER BY n DESC)
                    FROM unnest(string_to_array(data, ' ')) WITH ORDINALITY AS u(b, n)))::bit(64)::bigint
           * INTERVAL '1 microsecond' AS key
FROM bt_page_items('orders_ordered_at_idx', 289)
ORDER BY itemoffset
LIMIT 5;

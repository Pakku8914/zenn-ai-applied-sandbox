-- セッション3-5: リーフページはキーの順に並び、右隣のリーフへのリンク（btpo_next）を持つ
-- 先頭 4 枚のリーフ。btpo_prev / btpo_next が左右の隣のページ番号
SELECT blkno, type, live_items, free_size, btpo_prev, btpo_next, btpo_level
FROM bt_multi_page_stats('orders_ordered_at_idx', 1, 4);

-- 最初のリーフ（1 ページ目）の先頭 6 項目。htid がヒープ上の行の位置（ctid）
-- 1 番目の項目は「high key」（このページに入るキーの上限）で、行を指さない（htid が空）
SELECT itemoffset, ctid, htid, itemlen,
       TIMESTAMPTZ '2000-01-01 00:00:00+00'
         + ('x' || (SELECT string_agg(b, '' ORDER BY n DESC)
                    FROM unnest(string_to_array(data, ' ')) WITH ORDINALITY AS u(b, n)))::bit(64)::bigint
           * INTERVAL '1 microsecond' AS key
FROM bt_page_items('orders_ordered_at_idx', 1)
ORDER BY itemoffset
LIMIT 6;

-- htid でヒープの行を引くと、キーと同じ ordered_at を持つ注文が出てくる
SELECT o.ctid, o.id, o.ordered_at
FROM orders o
WHERE o.ctid IN ('(2623,99)', '(5247,76)', '(7871,53)')
ORDER BY o.ordered_at;

-- 1 ページ目の最後のキーと 2 ページ目の最初のキー: リーフをまたいでも順序が続いている
SELECT blkno, itemoffset,
       TIMESTAMPTZ '2000-01-01 00:00:00+00'
         + ('x' || (SELECT string_agg(b, '' ORDER BY n DESC)
                    FROM unnest(string_to_array(data, ' ')) WITH ORDINALITY AS u(b, n)))::bit(64)::bigint
           * INTERVAL '1 microsecond' AS key
FROM (SELECT 1 AS blkno, * FROM bt_page_items('orders_ordered_at_idx', 1)
      UNION ALL
      SELECT 2, * FROM bt_page_items('orders_ordered_at_idx', 2)) AS i
WHERE (blkno = 1 AND itemoffset IN (1, 367))
   OR (blkno = 2 AND itemoffset = 2)
ORDER BY blkno, itemoffset;

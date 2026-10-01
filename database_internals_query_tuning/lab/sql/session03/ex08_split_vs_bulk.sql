-- 演習 S03-ex08: INSERT で育てたインデックスと、CREATE INDEX で一括構築したインデックスの大きさの違い
-- 09_index_maintenance.sql の後に実行する（s03_ins_0 と s03_ins_1 に同じ 10 万行が入っている）
DROP INDEX IF EXISTS s03_ins_0_bulk_idx;
CREATE INDEX s03_ins_0_bulk_idx ON s03_ins_0 (ordered_at);

SELECT 's03_ins_1_ordered_at_idx（INSERT で育てた）' AS idx,
       pg_relation_size('s03_ins_1_ordered_at_idx') / 8192 AS pages,
       (SELECT round(avg(live_items), 1) FROM bt_multi_page_stats('s03_ins_1_ordered_at_idx', 1, -1) WHERE type = 'l') AS avg_leaf_items
UNION ALL
SELECT 's03_ins_0_bulk_idx（一括構築）',
       pg_relation_size('s03_ins_0_bulk_idx') / 8192,
       (SELECT round(avg(live_items), 1) FROM bt_multi_page_stats('s03_ins_0_bulk_idx', 1, -1) WHERE type = 'l');

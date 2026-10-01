-- 演習 S03-ex01: orders_ordered_at_idx の高さを答える（02_create_index.sql の後に実行）
SELECT root, level, level + 1 AS height FROM bt_metap('orders_ordered_at_idx');

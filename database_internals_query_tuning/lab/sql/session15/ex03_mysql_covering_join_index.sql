-- S15 演習：MySQL の Nested Loop を「セカンダリインデックスだけで」答えられるようにする
-- docker compose exec -T lab mysql --skip-ssl -h mysql -ulab shopdb -t < sql/session15/ex03_mysql_covering_join_index.sql
-- 既定の計画では、fk_orders_customer と fk_items_order で見つけた主キーの値で、1行ごとにクラスタ化インデックスを引き直している。
-- 結合に必要な列をすべて持つセカンダリインデックスを作ると、引き直しが消える（主キーの列はセカンダリインデックスに自動で入る）
-- 注意：外部キーの列で始まるインデックスを作ると、InnoDB は外部キー用に自動で作ったインデックス
--       （fk_orders_customer・fk_items_order）を黙って削除する。作業用インデックスが外部キーの支えになるので、
--       そのままでは DROP INDEX できない（ERROR 1553）。最後の後片付けまで必ず実行すること
CREATE INDEX s15_orders_customer_status_idx ON orders (customer_id, status);
CREATE INDEX s15_items_order_cover_idx ON order_items (order_id, product_id, quantity, unit_price);

EXPLAIN ANALYZE
WITH s AS (
  SELECT c.region, oi.product_id, SUM(oi.quantity * oi.unit_price) AS sales
  FROM orders o
  JOIN customers c ON c.id = o.customer_id
  JOIN order_items oi ON oi.order_id = o.id
  WHERE o.status <> 'cancelled'
  GROUP BY c.region, oi.product_id
), r AS (
  SELECT region, product_id, sales,
         ROW_NUMBER() OVER (PARTITION BY region ORDER BY sales DESC, product_id) AS rn
  FROM s
)
SELECT region, rn, product_id, sales FROM r WHERE rn <= 5 ORDER BY region, rn\G

-- 外部キー用のインデックスが消えていることを確かめる
SELECT table_name, index_name, GROUP_CONCAT(column_name ORDER BY seq_in_index) AS columns
FROM information_schema.statistics
WHERE table_schema = DATABASE() AND table_name IN ('orders', 'order_items')
GROUP BY table_name, index_name
ORDER BY table_name, index_name;

-- 後片付け：InnoDB が自動で作った外部キー用インデックスがある状態に戻す。
-- 外部キー制約をいったん外して作業用インデックスを消し、制約を付け直す（外部キー用インデックスが自動で作り直される）。
-- データは変えていないので、付け直すときの全行の検査は省く（foreign_key_checks = 0 はこのセッションだけに効く）
SET SESSION foreign_key_checks = 0;
ALTER TABLE orders DROP FOREIGN KEY fk_orders_customer;
DROP INDEX s15_orders_customer_status_idx ON orders;
ALTER TABLE orders ADD CONSTRAINT fk_orders_customer FOREIGN KEY (customer_id) REFERENCES customers (id), ALGORITHM = INPLACE;
ALTER TABLE order_items DROP FOREIGN KEY fk_items_order;
DROP INDEX s15_items_order_cover_idx ON order_items;
ALTER TABLE order_items ADD CONSTRAINT fk_items_order FOREIGN KEY (order_id) REFERENCES orders (id), ALGORITHM = INPLACE;
SET SESSION foreign_key_checks = 1;

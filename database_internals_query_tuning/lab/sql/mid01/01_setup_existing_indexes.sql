-- Mid01-01 題材のシステムに「もともと貼ってあるインデックス」を作る
-- 出発点（tools/reset.sh 直後）から実行する。3 本の遅いクエリは、このインデックスがすでにある状態で遅い
CREATE INDEX customers_email_idx ON customers (email);
CREATE INDEX orders_customer_id_idx ON orders (customer_id);
CREATE INDEX orders_ordered_at_idx ON orders (ordered_at);

-- 確認：どのテーブルにどのインデックスがあるか（主キーを含む）
SELECT tablename, indexname, indexdef
FROM pg_indexes
WHERE tablename IN ('customers', 'orders')
ORDER BY tablename, indexname;

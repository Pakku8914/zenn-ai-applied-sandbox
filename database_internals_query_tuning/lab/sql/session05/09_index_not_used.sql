-- 「インデックスがあるのに使われない」ケースを並べる。
-- 使われるか・使われないかは EXPLAIN（見積もりのみ）で十分に判断できる。
-- 前提: 01_create_indexes.sql 実行済み
CREATE INDEX customers_email_idx ON customers (email);
CREATE INDEX orders_status_idx ON orders (status);

-- (1) 列に関数を適用する
EXPLAIN SELECT * FROM customers WHERE email = 'user123@example.com';          -- 使われる
EXPLAIN SELECT * FROM customers WHERE lower(email) = 'user123@example.com';   -- 使われない

-- (2) 列を型変換する（timestamptz → date）
EXPLAIN SELECT * FROM orders WHERE ordered_at::date = '2025-06-01';           -- 使われない
EXPLAIN SELECT * FROM orders
WHERE ordered_at >= '2025-06-01' AND ordered_at < '2025-06-02';               -- 書き換え: 使われる

-- (3) 比較する値の型が列と合わない（integer の列に numeric の値）
EXPLAIN SELECT * FROM customers WHERE id = 12345.0;                           -- 使われない
EXPLAIN SELECT * FROM customers WHERE id = '12345';                           -- 使われる（文字列リテラルは列の型に合わせて解釈される）
EXPLAIN SELECT * FROM orders WHERE id = 12345::integer;                       -- 使われる（bigint と integer は比較演算子が用意されている）

-- (4) 前方一致は使われるが、後方一致・中間一致は使われない（照合順序 C のため前方一致を範囲に変換できる）
EXPLAIN SELECT * FROM customers WHERE email LIKE 'user123%';                  -- 使われる
EXPLAIN SELECT * FROM customers WHERE email LIKE '%123@example.com';          -- 使われない

-- (5) 否定条件
EXPLAIN SELECT * FROM orders WHERE status <> 'completed';                     -- 使われない
EXPLAIN SELECT * FROM orders WHERE status IN ('pending', 'cancelled');        -- 書き換え: 使われる

-- (6) OR の片側にインデックスのない列がある（orders.customer_id には外部キーはあるがインデックスはない）
EXPLAIN SELECT * FROM orders
WHERE (ordered_at >= '2025-06-01' AND ordered_at < '2025-06-01 01:00') OR id = 777;           -- 使われる（BitmapOr）
EXPLAIN SELECT * FROM orders
WHERE (ordered_at >= '2025-06-01' AND ordered_at < '2025-06-01 01:00') OR customer_id = 777;  -- 使われない

-- (7) 選択率が高すぎる（03 の (3) の再掲）
EXPLAIN SELECT * FROM customers WHERE region IN ('東京', '大阪', '名古屋');     -- 使われない

-- (1) の直し方: 式インデックスを作る（式の統計も取るため ANALYZE する）
CREATE INDEX customers_lower_email_idx ON customers (lower(email));
ANALYZE customers;
EXPLAIN SELECT * FROM customers WHERE lower(email) = 'user123@example.com';   -- 使われる

-- S08-06 ウィンドウ関数のコスト：WindowAgg は「PARTITION BY → ORDER BY の順に並んだ入力」を要求する
-- 05 で作った (customer_id, ordered_at) の複合インデックスがあるとソートが消えるので、いったん消してから始める
DROP INDEX IF EXISTS orders_customer_id_ordered_at_idx;

-- (1) 顧客ごとの注文順位：前段に Sort（customer_id, ordered_at）が入る
EXPLAIN (ANALYZE, BUFFERS)
SELECT customer_id, id, ordered_at,
       row_number() OVER (PARTITION BY customer_id ORDER BY ordered_at) AS nth
FROM orders;

-- (2) 顧客ごとの最初の注文だけを取る：Run Condition により、各顧客の 2 件目以降は WindowAgg の段階で打ち切られる
EXPLAIN (ANALYZE, BUFFERS)
SELECT customer_id, id, ordered_at
FROM (
  SELECT customer_id, id, ordered_at,
         row_number() OVER (PARTITION BY customer_id ORDER BY ordered_at) AS nth
  FROM orders
) AS s
WHERE nth = 1;

-- (3) 件数の確認（顧客 5 万人それぞれの最初の注文）
SELECT count(*) AS first_orders
FROM (
  SELECT row_number() OVER (PARTITION BY customer_id ORDER BY ordered_at) AS nth
  FROM orders
) AS s
WHERE nth = 1;

-- (4) PARTITION BY と ORDER BY に合う複合インデックスがあれば、Sort なしで WindowAgg に渡せる
CREATE INDEX orders_customer_id_ordered_at_idx ON orders (customer_id, ordered_at);
EXPLAIN (ANALYZE, BUFFERS)
SELECT customer_id, id, ordered_at,
       row_number() OVER (PARTITION BY customer_id ORDER BY ordered_at) AS nth
FROM orders;

-- (5) 並べ方の違うウィンドウを 2 つ使うと、それぞれに Sort が必要になる
EXPLAIN (ANALYZE, BUFFERS)
SELECT customer_id, id, ordered_at,
       row_number() OVER (PARTITION BY customer_id ORDER BY ordered_at) AS nth_in_customer,
       rank() OVER (ORDER BY ordered_at) AS nth_overall
FROM orders
WHERE ordered_at >= '2025-03-01' AND ordered_at < '2025-03-02';

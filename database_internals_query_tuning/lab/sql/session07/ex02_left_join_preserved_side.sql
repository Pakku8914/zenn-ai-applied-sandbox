-- S07 練習問題の模範解答：LEFT JOIN で「残したい側（左側）」の条件をどこに書くか
-- 「東京の顧客全員について、2025年3月1日〜5日の注文を並べる（注文の無い顧客も残す）」

-- (1) 左側の条件を ON に書く（誤り）：東京以外の顧客も 1 行ずつ残り、orders 側がすべて NULL になる
SELECT count(*) AS result_rows, count(o.id) AS matched_orders
FROM customers c
LEFT JOIN orders o
  ON o.customer_id = c.id
 AND o.ordered_at >= '2025-03-01' AND o.ordered_at < '2025-03-06'
 AND c.region = '東京';

-- (2) 左側の条件は WHERE、右側の条件は ON に書く（正しい）
SELECT count(*) AS result_rows, count(o.id) AS matched_orders
FROM customers c
LEFT JOIN orders o
  ON o.customer_id = c.id
 AND o.ordered_at >= '2025-03-01' AND o.ordered_at < '2025-03-06'
WHERE c.region = '東京';

-- (3) 右側の条件まで WHERE に書く（誤り）：注文の無い東京の顧客が消える
SELECT count(*) AS result_rows, count(o.id) AS matched_orders
FROM customers c
LEFT JOIN orders o ON o.customer_id = c.id
WHERE c.region = '東京'
  AND o.ordered_at >= '2025-03-01' AND o.ordered_at < '2025-03-06';

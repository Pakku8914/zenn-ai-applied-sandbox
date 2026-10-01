-- S07-08 LEFT JOIN の条件を ON に書くか WHERE に書くかで、結果の件数が変わる
-- 「全顧客について、2025年3月1日〜5日の注文を並べる（注文の無い顧客も 1 行出す）」つもりのクエリ

-- (1) 条件を ON に書く：注文の無い顧客も残る（orders 側の列が NULL の行として）
SELECT count(*) AS result_rows, count(o.id) AS matched_orders
FROM customers c
LEFT JOIN orders o
  ON o.customer_id = c.id
 AND o.ordered_at >= '2025-03-01' AND o.ordered_at < '2025-03-06';

-- (2) 条件を WHERE に書く：NULL の行が WHERE で落ち、結果として内部結合と同じになる
SELECT count(*) AS result_rows, count(o.id) AS matched_orders
FROM customers c
LEFT JOIN orders o ON o.customer_id = c.id
WHERE o.ordered_at >= '2025-03-01' AND o.ordered_at < '2025-03-06';

-- (3) 左側（残したい側）の条件を ON に書いても、左側の行は減らない
SELECT count(*) AS result_rows, count(o.id) AS matched_orders
FROM customers c
LEFT JOIN orders o
  ON o.customer_id = c.id
 AND o.ordered_at >= '2025-03-01' AND o.ordered_at < '2025-03-06'
 AND c.region = '東京';

-- (4) 実行計画：ON 版は Hash Right Join（全顧客を残す）、WHERE 版は Left の付かない内部結合に書き換えられる
EXPLAIN (ANALYZE, BUFFERS)
SELECT count(*) AS result_rows, count(o.id) AS matched_orders
FROM customers c
LEFT JOIN orders o
  ON o.customer_id = c.id
 AND o.ordered_at >= '2025-03-01' AND o.ordered_at < '2025-03-06';

EXPLAIN (ANALYZE, BUFFERS)
SELECT count(*) AS result_rows, count(o.id) AS matched_orders
FROM customers c
LEFT JOIN orders o ON o.customer_id = c.id
WHERE o.ordered_at >= '2025-03-01' AND o.ordered_at < '2025-03-06';

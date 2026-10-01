-- Review02 練習問題の模範解答：「全顧客の 2025年3月1日の売上（注文が無ければ 0 円）」（S07 の復習）
-- 売上は cancelled 以外。キャンセルの条件をどこに書くかで、顧客の数が変わる

-- (1) 誤り：キャンセル除外を WHERE に書いた。LEFT JOIN が内部結合と同じになり、注文の無い顧客が消える
SELECT count(*) AS customers, sum(sales) AS total_sales
FROM (
  SELECT c.id, coalesce(sum(oi.quantity * oi.unit_price), 0) AS sales
  FROM customers c
  LEFT JOIN orders o ON o.customer_id = c.id
   AND o.ordered_at >= '2025-03-01' AND o.ordered_at < '2025-03-02'
  LEFT JOIN order_items oi ON oi.order_id = o.id
  WHERE o.status <> 'cancelled'
  GROUP BY c.id
) AS s;

-- (2) 正しい：orders 側の条件はすべて ON に書く
SELECT count(*) AS customers, sum(sales) AS total_sales
FROM (
  SELECT c.id, coalesce(sum(oi.quantity * oi.unit_price), 0) AS sales
  FROM customers c
  LEFT JOIN orders o ON o.customer_id = c.id
   AND o.ordered_at >= '2025-03-01' AND o.ordered_at < '2025-03-02'
   AND o.status <> 'cancelled'
  LEFT JOIN order_items oi ON oi.order_id = o.id
  GROUP BY c.id
) AS s;

-- (3) 売上 0 円の顧客の数
SELECT count(*) AS zero_sales_customers
FROM (
  SELECT c.id, coalesce(sum(oi.quantity * oi.unit_price), 0) AS sales
  FROM customers c
  LEFT JOIN orders o ON o.customer_id = c.id
   AND o.ordered_at >= '2025-03-01' AND o.ordered_at < '2025-03-02'
   AND o.status <> 'cancelled'
  LEFT JOIN order_items oi ON oi.order_id = o.id
  GROUP BY c.id
) AS s
WHERE sales = 0;

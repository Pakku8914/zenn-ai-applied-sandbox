-- Review02 練習問題の模範解答：相関のある 2 条件の見積もり外れは、結合の計画を変えたか（S06 の復習）
-- customers の region は created_at から決まる（強い相関）。2024-01-02 に登録した顧客は全員「大阪」
-- 顧客の注文を引くため、02 と同じ複合インデックスを用意しておく（03 で消していれば作り直す）
CREATE INDEX IF NOT EXISTS orders_customer_id_ordered_at_idx ON orders (customer_id, ordered_at);

-- (1) 拡張統計なし：customers の見積もりは実際の約 1/5
EXPLAIN (ANALYZE)
SELECT count(*)
FROM customers c
JOIN orders o ON o.customer_id = c.id
WHERE c.region = '大阪' AND c.created_at = '2024-01-02';

-- (2) 関数従属の拡張統計を作って ANALYZE する
CREATE STATISTICS customers_region_created_at_dep (dependencies) ON region, created_at FROM customers;
ANALYZE customers;
-- 列番号 4 = region、5 = created_at。"5 => 4" が created_at から region が決まる度合い
SELECT statistics_name, dependencies FROM pg_stats_ext WHERE statistics_name = 'customers_region_created_at_dep';

-- (3) 拡張統計あり：見積もりは合うが、計画の形は変わらない
EXPLAIN (ANALYZE)
SELECT count(*)
FROM customers c
JOIN orders o ON o.customer_id = c.id
WHERE c.region = '大阪' AND c.created_at = '2024-01-02';

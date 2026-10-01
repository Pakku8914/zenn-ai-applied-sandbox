-- Review02 練習問題の模範解答：期間を広げるとスキャン方式はどこで切り替わるか（S05 の復習）
-- orders(ordered_at) のインデックスを作り、SELECT *（ヒープを読む必要がある）と count(*)（インデックスだけで済む）で比べる
CREATE INDEX IF NOT EXISTS orders_ordered_at_idx ON orders (ordered_at);

-- (1) SELECT *：1 日・1 か月・3 か月・6 か月
EXPLAIN (COSTS OFF) SELECT * FROM orders WHERE ordered_at >= '2025-03-01' AND ordered_at < '2025-03-02';
EXPLAIN (COSTS OFF) SELECT * FROM orders WHERE ordered_at >= '2025-03-01' AND ordered_at < '2025-04-01';
EXPLAIN (COSTS OFF) SELECT * FROM orders WHERE ordered_at >= '2025-01-01' AND ordered_at < '2025-04-01';
EXPLAIN (COSTS OFF) SELECT * FROM orders WHERE ordered_at >= '2025-01-01' AND ordered_at < '2025-07-01';

-- (2) count(*)：6 か月でもインデックスだけで数えられる
EXPLAIN (COSTS OFF) SELECT count(*) FROM orders WHERE ordered_at >= '2025-01-01' AND ordered_at < '2025-07-01';

-- (3) 件数（選択率の確認）
SELECT count(*) FILTER (WHERE ordered_at >= '2025-03-01' AND ordered_at < '2025-03-02') AS one_day,
       count(*) FILTER (WHERE ordered_at >= '2025-03-01' AND ordered_at < '2025-04-01') AS one_month,
       count(*) FILTER (WHERE ordered_at >= '2025-01-01' AND ordered_at < '2025-04-01') AS three_months,
       count(*) FILTER (WHERE ordered_at >= '2025-01-01' AND ordered_at < '2025-07-01') AS six_months
FROM orders;

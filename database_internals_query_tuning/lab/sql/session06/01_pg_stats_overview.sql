-- S06 の出発点: tools/reset.sh の直後に実行する（統計は reset.sh の ANALYZE で取り直されている）。
-- pg_stats は ANALYZE が標本（既定 30,000 行）から作った列ごとの統計。値は標本抽出で少しずつ揺れる。

-- (1) 列ごとの要約: NULL の割合・異なり数・物理順との相関
SELECT tablename, attname, null_frac, n_distinct, correlation
FROM pg_stats
WHERE schemaname = 'public' AND tablename IN ('orders', 'customers')
ORDER BY tablename, attname;

-- (2) 最頻値（MCV）とその頻度: orders.status と customers.region
SELECT tablename, attname, most_common_vals, most_common_freqs
FROM pg_stats
WHERE (tablename, attname) IN (('orders', 'status'), ('customers', 'region'));

-- (3) ヒストグラム: orders.ordered_at は値がほぼすべて異なるので MCV を持たず、101 個の境界値（100 個の区間）で分布を表す
SELECT array_length(histogram_bounds, 1) AS 境界値の数,
       (histogram_bounds::text::timestamptz[])[1:4] AS 先頭の4つ,
       (histogram_bounds::text::timestamptz[])[98:101] AS 末尾の4つ
FROM pg_stats WHERE tablename = 'orders' AND attname = 'ordered_at';

-- (4) 実際の値と比べる
SELECT status, count(*), round(count(*) / 1000000.0, 4) AS 割合
FROM orders GROUP BY status ORDER BY count(*) DESC;
SELECT count(DISTINCT customer_id) AS customer_id_の異なり数 FROM orders;

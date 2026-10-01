-- 物理的な並び順と完全に相関する orders.id の範囲で、
-- Index Scan → Seq Scan に切り替わる境界を二分探索で探す。
-- プランの形と見積もりを見るだけなので ANALYZE は付けない（一瞬で終わる）。
-- psql の変数 :n を \set で書き換えながら実行する。
-- 前提: 01_create_indexes.sql 実行済み

-- 出発点: 下端（Index Scan になる値）と上端（Seq Scan になる値）を 1 つずつ見つける
\set n 500000
EXPLAIN SELECT * FROM orders WHERE id BETWEEN 1 AND :n;

\set n 700000
EXPLAIN SELECT * FROM orders WHERE id BETWEEN 1 AND :n;

-- 真ん中を試し、結果が Index Scan なら下端を、Seq Scan なら上端をそこへ動かす
\set n 600000
EXPLAIN SELECT * FROM orders WHERE id BETWEEN 1 AND :n;

\set n 550000
EXPLAIN SELECT * FROM orders WHERE id BETWEEN 1 AND :n;

-- …これを上端と下端の差が 1 になるまで繰り返す（約 18 回）。
-- 境界の値は ANALYZE の標本抽出で数千ほど前後する。見積もり行数 rows= で見ると毎回ほぼ同じ所で切り替わる。

-- 参考: この列が物理順とどれだけ相関しているか（S06 で詳しく扱う）
SELECT attname, correlation FROM pg_stats
WHERE tablename = 'orders' AND attname IN ('id', 'ordered_at')
ORDER BY attname;

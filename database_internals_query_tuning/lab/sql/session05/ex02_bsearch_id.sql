-- 練習（模範解答）: id の範囲で Index Scan → Seq Scan の境界を二分探索する。
-- 前提: 01_create_indexes.sql 実行済み
-- 手順: 下端 lo（Index Scan）と上端 hi（Seq Scan）を決め、mid = (lo + hi) / 2 を試して片側を mid に動かす。
--       hi - lo = 1 になったら終わり。境界の値は ANALYZE の標本抽出で数千前後するので、見積もり rows= も記録する。
\set n 500000
EXPLAIN SELECT * FROM orders WHERE id BETWEEN 1 AND :n;
\set n 700000
EXPLAIN SELECT * FROM orders WHERE id BETWEEN 1 AND :n;
\set n 600000
EXPLAIN SELECT * FROM orders WHERE id BETWEEN 1 AND :n;
\set n 550000
EXPLAIN SELECT * FROM orders WHERE id BETWEEN 1 AND :n;
\set n 575000
EXPLAIN SELECT * FROM orders WHERE id BETWEEN 1 AND :n;
-- …以下、hi - lo = 1 まで続ける

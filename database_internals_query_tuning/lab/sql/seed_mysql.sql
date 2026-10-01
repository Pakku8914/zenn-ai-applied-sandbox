-- MySQL 側の決定的なデータ投入（PostgreSQL 側と同じ分布・同じ行数になるようにしてある）。
-- MySQL には generate_series がないので、0〜9 の表を CROSS JOIN して 10^6 行を作る。
-- 再帰 CTE を使わないのは、cte_max_recursion_depth の引き上げが必要になり遅いため。
-- 日本語を正しく送る。同梱のクライアント（MariaDB 系）は既定で latin1 を使うため、
-- 指定しないと UTF-8 のバイト列が latin1 の文字として解釈され、二重にエンコードされて保存される
SET NAMES utf8mb4;

SET FOREIGN_KEY_CHECKS = 0;
TRUNCATE TABLE order_items;
TRUNCATE TABLE orders;
TRUNCATE TABLE products;
TRUNCATE TABLE customers;
SET FOREIGN_KEY_CHECKS = 1;

-- 一時テーブル（TEMPORARY）は同一クエリ内で複数回参照できない（ERROR 1137: Can't reopen table）。
-- CROSS JOIN で同じ表を6回使うため、通常テーブルとして作り最後に削除する。
DROP TABLE IF EXISTS seq10;
CREATE TABLE seq10 (i INT NOT NULL) ENGINE=InnoDB;
INSERT INTO seq10 (i) VALUES (0),(1),(2),(3),(4),(5),(6),(7),(8),(9);

-- 各 INSERT の ORDER BY は省略しない。CROSS JOIN が行を返す順序は決まっていないため、
-- 主キーの順に挿入しないとページ分割でページ数が投入のたびに変わり、
-- order_items では AUTO_INCREMENT の id と行の対応が PostgreSQL 側とずれる。
-- PostgreSQL 側（seed_pg.sql）は「全注文の 1 行目 → 2 行目 → 3 行目」の順に id が振られるので、同じ順にする

-- 顧客 50,000 件
INSERT INTO customers (id, name, email, region, created_at)
SELECT n.i,
       CONCAT('顧客', n.i),
       CONCAT('user', n.i, '@example.com'),
       ELT(1 + (n.i % 5), '東京', '大阪', '名古屋', '福岡', '札幌'),
       DATE_ADD('2024-01-01 00:00:00', INTERVAL (n.i % 700) DAY)
FROM (
  SELECT a.i + b.i * 10 + c.i * 100 + d.i * 1000 + e.i * 10000 + 1 AS i
  FROM seq10 a, seq10 b, seq10 c, seq10 d, seq10 e
) AS n
WHERE n.i <= 50000
ORDER BY n.i;

-- 商品 5,000 件
INSERT INTO products (id, name, category, price, stock)
SELECT n.i,
       CONCAT('商品', n.i),
       ELT(1 + (n.i % 4), '文具', '書籍', '雑貨', '食品'),
       100 + (n.i * 37 % 9900),
       (n.i * 13 % 500)
FROM (
  SELECT a.i + b.i * 10 + c.i * 100 + d.i * 1000 + 1 AS i
  FROM seq10 a, seq10 b, seq10 c, seq10 d
) AS n
WHERE n.i <= 5000
ORDER BY n.i;

-- 注文 1,000,000 件
INSERT INTO orders (id, customer_id, ordered_at, status)
SELECT n.i,
       1 + (n.i * 7919 % 50000),
       DATE_ADD(DATE_ADD('2025-01-01 00:00:00', INTERVAL (n.i % 365) DAY),
                INTERVAL (n.i * 61 % 86400) SECOND),
       CASE WHEN n.i % 23 = 0 THEN 'cancelled'
            WHEN n.i % 7  = 0 THEN 'pending'
            ELSE 'completed' END
FROM (
  SELECT a.i + b.i * 10 + c.i * 100 + d.i * 1000 + e.i * 10000 + f.i * 100000 + 1 AS i
  FROM seq10 a, seq10 b, seq10 c, seq10 d, seq10 e, seq10 f
) AS n
WHERE n.i <= 1000000
ORDER BY n.i;

-- 注文明細（1注文あたり 1〜3 行。PostgreSQL 側と同じ式）
INSERT INTO order_items (order_id, product_id, quantity, unit_price)
SELECT o.id,
       1 + ((o.id * 104729 + k.i) % 5000),
       1 + ((o.id + k.i) % 3),
       100 + ((o.id * 31 + k.i) % 900)
FROM orders o
JOIN (SELECT 0 AS i UNION ALL SELECT 1 UNION ALL SELECT 2) AS k
  ON k.i <= (o.id % 3)
ORDER BY k.i, o.id;

DROP TABLE seq10;

ANALYZE TABLE customers, products, orders, order_items;

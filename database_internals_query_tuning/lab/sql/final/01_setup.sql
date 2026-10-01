-- Final-01 「注文管理画面が重い」と報告されたシステムを再現する（出発点から 5 秒ほど。何度実行してもよい）
-- 4 テーブル（customers / products / orders / order_items）の行は変えない。在庫と出荷待ちは作業用テーブル（final_ 接頭辞）に置く
-- 使い方: \i sql/final/01_setup.sql
-- 10 や練習問題で作ったインデックス・作業用テーブルが残っていれば消して、改善前の状態に戻す
SET client_min_messages = warning;
DROP TABLE IF EXISTS final_products, final_ship_queue;
DROP SEQUENCE IF EXISTS final_order_id_seq;
DROP INDEX IF EXISTS orders_status_idx, orders_customer_id_idx, orders_ordered_at_idx,
                     order_items_order_id_idx, order_items_order_id_plain_idx;
RESET client_min_messages;

-- (1) このシステムにもともとあるインデックス。主キー以外はこの 1 本だけ（昔の集計バッチのために作られた）
CREATE INDEX orders_status_idx ON orders (status);

-- (2) 在庫引き当て用の商品テーブル（products のコピー）。
--     引き当ての「待ち」を観察する実験なので、在庫切れが起きないよう全商品の在庫を 10 万個にそろえる
CREATE TABLE final_products AS
SELECT id, name, category, price, 100000 AS stock FROM products ORDER BY id;
ALTER TABLE final_products ADD PRIMARY KEY (id);

-- (3) 出荷待ちキュー。注文が入ると 1 行積まれ、出荷されると DELETE される。
--     1 年分の注文を一括で積み直したときに autovacuum を止め、そのまま戻し忘れた（という設定）
CREATE TABLE final_ship_queue (
  order_id    bigint      PRIMARY KEY,
  customer_id integer     NOT NULL,
  region      text        NOT NULL,   -- 出荷先の地域（地域ごとに倉庫の担当者が分かれている）
  ordered_at  timestamptz NOT NULL
) WITH (autovacuum_enabled = false);
INSERT INTO final_ship_queue
SELECT o.id, o.customer_id, c.region, o.ordered_at
FROM orders o JOIN customers c ON c.id = o.customer_id
WHERE o.status <> 'cancelled'
ORDER BY o.ordered_at;
ANALYZE final_ship_queue;               -- 一括投入の直後に 1 回だけ統計を取った
DELETE FROM final_ship_queue            -- その後 1 年かけて出荷された分（12/26 までの注文）が消えた
WHERE ordered_at < '2025-12-27';

-- (4) 引き当てで作る新しい注文の番号
CREATE SEQUENCE final_order_id_seq START 2000001;

VACUUM (ANALYZE) final_products;

-- できあがった状態：出荷待ちは 5 日分（12/27〜12/31）だけが残っている
SELECT count(*) AS waiting_orders, min(ordered_at)::date AS oldest, max(ordered_at)::date AS newest
FROM final_ship_queue;

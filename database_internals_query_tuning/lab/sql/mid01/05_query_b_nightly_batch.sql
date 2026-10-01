-- Mid01-05 遅いクエリ B の舞台：夜間バッチの取り込みテーブル mid01_import
-- 毎晩 TRUNCATE してから、その日の注文明細を入れ直す。ANALYZE は「昨夜」の取り込みの直後に一度だけ走った、という状態を再現する
-- autovacuum を止めているのは、この環境（autovacuum_naptime = 10s）では自動 ANALYZE が先に走り、再現しないことがあるため
DROP TABLE IF EXISTS mid01_import;
CREATE TABLE mid01_import (
    batch_date date    NOT NULL,  -- 取り込んだ注文の日付
    order_id   bigint  NOT NULL,
    line_no    integer NOT NULL,  -- 注文の中の明細番号（1 から）
    product_id integer NOT NULL,
    quantity   integer NOT NULL,
    unit_price integer NOT NULL
) WITH (autovacuum_enabled = false);

-- 昨夜（2025-12-30 分）の取り込み。この直後に ANALYZE が走った
INSERT INTO mid01_import
SELECT o.ordered_at::date, oi.order_id,
       row_number() OVER (PARTITION BY oi.order_id ORDER BY oi.id),
       oi.product_id, oi.quantity, oi.unit_price
FROM order_items oi
JOIN orders o ON o.id = oi.order_id
WHERE o.ordered_at >= '2025-12-30' AND o.ordered_at < '2025-12-31';
-- 変更行数の集計はしばらく接続の中に溜められてから送られる（S06）。ANALYZE の後の変更に数えられないよう、先に書き出させる
SELECT pg_stat_force_next_flush();
SELECT pg_sleep(1);
ANALYZE mid01_import;

-- 今夜（2025-12-31 分）：TRUNCATE して入れ直す。ANALYZE はまだ走っていない
TRUNCATE mid01_import;
INSERT INTO mid01_import
SELECT o.ordered_at::date, oi.order_id,
       row_number() OVER (PARTITION BY oi.order_id ORDER BY oi.id),
       oi.product_id, oi.quantity, oi.unit_price
FROM order_items oi
JOIN orders o ON o.id = oi.order_id
WHERE o.ordered_at >= '2025-12-31' AND o.ordered_at < '2026-01-01';

-- 取り込み元の再送で、注文番号の小さい 3 件の 1 行目が二重に届いた（重複チェックで見つけたいもの）
INSERT INTO mid01_import
SELECT batch_date, order_id, line_no + 10, product_id, quantity, unit_price
FROM mid01_import
WHERE line_no = 1
  AND order_id IN (SELECT DISTINCT order_id FROM mid01_import ORDER BY order_id LIMIT 3);

SELECT batch_date, count(*) AS lines, count(DISTINCT order_id) AS orders
FROM mid01_import
GROUP BY batch_date;

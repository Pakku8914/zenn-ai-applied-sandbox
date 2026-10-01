-- セッション3（MySQL 比較）: InnoDB のセカンダリインデックス
-- 先に tools/reset.sh で出発点に戻してから実行する（2 回目は CREATE INDEX が重複で失敗するため）
-- 使い方: docker compose exec -T lab mysql --skip-ssl -h mysql -ulab shopdb -t < sql/session03/mysql_01_secondary_index.sql

-- インデックスなし: テーブル全体（クラスタ化インデックス）を読む
EXPLAIN FORMAT=TREE
SELECT * FROM orders WHERE ordered_at >= '2025-06-01' AND ordered_at < '2025-06-02'\G

-- セカンダリインデックスの合計サイズ（作る前。外部キー用の fk_orders_customer だけ）
SELECT index_length, index_length DIV 16384 AS pages
FROM information_schema.tables WHERE table_schema = DATABASE() AND table_name = 'orders';

CREATE INDEX idx_orders_ordered_at ON orders (ordered_at);
ANALYZE TABLE orders;

-- 作った後（差が idx_orders_ordered_at の大きさ）
SELECT index_length, index_length DIV 16384 AS pages
FROM information_schema.tables WHERE table_schema = DATABASE() AND table_name = 'orders';

-- インデックスあり: 範囲スキャン。PostgreSQL の Bitmap Heap Scan にあたる仕組みはない
EXPLAIN ANALYZE
SELECT * FROM orders WHERE ordered_at >= '2025-06-01' AND ordered_at < '2025-06-02'\G

-- セカンダリインデックスのリーフは「キー + 主キーの値」を持つ。
-- 主キー（id）だけを返すなら本体を読まずに済む（Covering index range scan）
EXPLAIN ANALYZE
SELECT id FROM orders WHERE ordered_at >= '2025-06-01' AND ordered_at < '2025-06-02'\G

-- 同じ理由で、SELECT id だけの全件読みは、本体より小さいセカンダリインデックス（外部キー用）を読むことがある。
-- すると ORDER BY がないときの並びは customer_id の順になる
EXPLAIN FORMAT=TREE SELECT id FROM orders LIMIT 3\G
SELECT id FROM orders LIMIT 3;

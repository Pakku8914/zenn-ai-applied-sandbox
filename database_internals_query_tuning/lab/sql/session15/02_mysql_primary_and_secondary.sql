-- S15-02 MySQL（InnoDB のクラスタ化インデックス）：01 と同じクエリ
-- docker compose exec -T lab mysql --skip-ssl -h mysql -ulab shopdb -t < sql/session15/02_mysql_primary_and_secondary.sql
-- 先に出発点へ戻しておく: docker compose exec lab bash tools/reset.sh（MySQL 側のインデックスも片付く）

-- (1) ordered_at のインデックスを作る（リーフは「キー + 主キーの値」を持つ）
CREATE INDEX orders_ordered_at_idx ON orders (ordered_at);

-- (2) 主キー順の範囲読み：テーブル本体が主キーの B+木なので、リーフを順にたどるだけ
EXPLAIN ANALYZE
SELECT * FROM orders WHERE id BETWEEN 200001 AND 300000\G

-- (3) 1週間分の id と ordered_at だけを取る：セカンダリインデックスだけで答えられる（Covering）
EXPLAIN ANALYZE
SELECT id, ordered_at FROM orders
WHERE ordered_at >= '2025-06-01' AND ordered_at < '2025-06-08'\G

-- (4) 全列を取る：見つけた主キーの値で、1行ごとにクラスタ化インデックスをルートから引き直す
EXPLAIN ANALYZE
SELECT * FROM orders
WHERE ordered_at >= '2025-06-01' AND ordered_at < '2025-06-08'\G

-- (5) 参考：主キーの値を並べ替えてからまとめて引く Multi-Range Read（PostgreSQL の Bitmap Heap Scan に近い発想）。
--     既定ではコストで判断して使われない。セッションだけで強制して計画の表示を見る
SET SESSION optimizer_switch = 'mrr_cost_based=off';
EXPLAIN ANALYZE
SELECT * FROM orders
WHERE ordered_at >= '2025-06-01' AND ordered_at < '2025-06-08'\G
SET SESSION optimizer_switch = 'default';

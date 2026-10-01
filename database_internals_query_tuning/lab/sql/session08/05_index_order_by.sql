-- S08-05 インデックスでソートを省略できる条件
-- B+木のリーフはキーの順に並んでいるので、ORDER BY がインデックスの並びと一致すれば、読むだけで並んだ結果になる

-- (1) インデックスなし：全件を読み、Top-N ソートで最初の 10 件を選ぶ
EXPLAIN (ANALYZE, BUFFERS)
SELECT * FROM orders ORDER BY ordered_at LIMIT 10;

-- (2) ordered_at のインデックスを作る：先頭から 10 件読んだら終わり（Sort ノードが消える）
CREATE INDEX orders_ordered_at_idx ON orders (ordered_at);
EXPLAIN (ANALYZE, BUFFERS)
SELECT * FROM orders ORDER BY ordered_at LIMIT 10;

-- (3) 逆順も同じインデックスを後ろから読める（Index Scan Backward）
EXPLAIN (ANALYZE, BUFFERS)
SELECT * FROM orders ORDER BY ordered_at DESC LIMIT 10;

-- (4) ORDER BY の先頭だけがインデックスと一致：Incremental Sort（先頭キーが同じ小さな塊だけを並べ直す）
EXPLAIN (ANALYZE, BUFFERS)
SELECT * FROM orders ORDER BY ordered_at, id LIMIT 10;

-- (5) 列に関数をかけた式で並べると、そのインデックスは使えない
EXPLAIN (ANALYZE, BUFFERS)
SELECT * FROM orders ORDER BY date_trunc('day', ordered_at) LIMIT 10;

-- (6) WHERE がよく当たる条件なら、インデックス順に読みながら条件で捨てていけばすぐ 10 件そろう
EXPLAIN (ANALYZE, BUFFERS)
SELECT * FROM orders WHERE status = 'pending' ORDER BY ordered_at LIMIT 10;

-- (7) WHERE がめったに当たらない条件（1 顧客の注文は 20 件）だと、ordered_at のインデックスは役に立たず、ソートが残る
EXPLAIN (ANALYZE, BUFFERS)
SELECT * FROM orders WHERE customer_id = 777 ORDER BY ordered_at DESC LIMIT 10;

-- (8) WHERE の等値条件の列を先頭に、ORDER BY の列を 2 番目に置いた複合インデックスなら、絞り込みと並びを同時に満たせる
CREATE INDEX orders_customer_id_ordered_at_idx ON orders (customer_id, ordered_at);
EXPLAIN (ANALYZE, BUFFERS)
SELECT * FROM orders WHERE customer_id = 777 ORDER BY ordered_at DESC LIMIT 10;

-- (9) LIMIT なしで全件を ordered_at 順に返す場合も、この環境ではインデックス順に読むプランが選ばれた
EXPLAIN (ANALYZE, BUFFERS)
SELECT * FROM orders ORDER BY ordered_at;

-- (10) 比較用：インデックスを使わせないと Seq Scan ＋ 外部ソートになる
SET enable_indexscan = off;
SET enable_bitmapscan = off;
EXPLAIN (ANALYZE, BUFFERS)
SELECT * FROM orders ORDER BY ordered_at;
RESET enable_indexscan;
RESET enable_bitmapscan;

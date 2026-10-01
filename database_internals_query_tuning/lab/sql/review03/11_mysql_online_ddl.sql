-- R03-11 MySQL ではどうなるか：オンライン DDL の ALGORITHM 指定で「書き換えが要るか」をあらかじめ確かめる
-- docker compose exec lab mysql --skip-ssl -h mysql -ulab shopdb で入り、上から順に貼る（メモリ節約のためコピーは 20 万行）
-- ALGORITHM=INSTANT はメタデータだけを変える。できない変更はエラーで断られる（実行されない）ので、本番前の確認に使える

-- [A1] セッションA: 作業用コピーを作る
DROP TABLE IF EXISTS r03_orders;
CREATE TABLE r03_orders (PRIMARY KEY (id)) AS SELECT * FROM orders WHERE id <= 200000;

-- [A2] セッションA: 列の追加は INSTANT でできる。型の変更（int → bigint）は INSTANT も INPLACE もできず、COPY（書き換え）になる
ALTER TABLE r03_orders ADD COLUMN note TEXT, ALGORITHM=INSTANT;
ALTER TABLE r03_orders MODIFY customer_id BIGINT NOT NULL, ALGORITHM=INSTANT;
ALTER TABLE r03_orders MODIFY customer_id BIGINT NOT NULL, ALGORITHM=INPLACE;
ALTER TABLE r03_orders MODIFY customer_id BIGINT NOT NULL, ALGORITHM=COPY;

-- [A3] セッションA: インデックスの追加は、書き込みを止めずに（LOCK=NONE）その場で作れる
ALTER TABLE r03_orders ADD INDEX r03_orders_customer_idx (customer_id), ALGORITHM=INPLACE, LOCK=NONE;
DROP TABLE r03_orders;

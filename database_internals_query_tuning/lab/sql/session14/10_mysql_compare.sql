-- S14-10 MySQL ではどうなるか（mysql クライアントで実行する：docker compose exec lab mysql --skip-ssl -h mysql -ulab shopdb）
-- source sql/session14/10_mysql_compare.sql でも実行できる。サーバーの設定（SET GLOBAL）は変えない。表示するだけ
-- (1) バッファプールの大きさと、ファイルの読み書きのしかた（O_DIRECT は OS のキャッシュを通さない）
SHOW VARIABLES WHERE Variable_name IN ('innodb_buffer_pool_size', 'innodb_page_size', 'innodb_flush_method',
  'innodb_old_blocks_pct', 'innodb_old_blocks_time');

-- (2) バッファプールの全体像：枠の数・空き・データのページ・そのうち old 側・ダーティなページ
SELECT POOL_SIZE, FREE_BUFFERS, DATABASE_PAGES, OLD_DATABASE_PAGES, MODIFIED_DATABASE_PAGES
FROM information_schema.INNODB_BUFFER_POOL_STATS;

-- (3) orders を全件読む前後で、論理読み取り（read_requests）とディスクからの読み取り（reads）を比べる。2 回続けて実行する
--     status の長さを合計させて、行データを持つクラスタ化インデックス（PRIMARY）を端から読ませる
--     （COUNT(*) だけだと、InnoDB は一番小さいセカンダリインデックスを読んで数える）
SELECT VARIABLE_NAME, VARIABLE_VALUE FROM performance_schema.global_status
WHERE VARIABLE_NAME IN ('Innodb_buffer_pool_read_requests', 'Innodb_buffer_pool_reads');
SELECT SUM(LENGTH(status)) FROM orders;
SELECT VARIABLE_NAME, VARIABLE_VALUE FROM performance_schema.global_status
WHERE VARIABLE_NAME IN ('Innodb_buffer_pool_read_requests', 'Innodb_buffer_pool_reads');
SELECT SUM(LENGTH(status)) FROM orders;
SELECT VARIABLE_NAME, VARIABLE_VALUE FROM performance_schema.global_status
WHERE VARIABLE_NAME IN ('Innodb_buffer_pool_read_requests', 'Innodb_buffer_pool_reads');

-- (4) このデータベースのどのテーブル・インデックスが何ページ載っているか（PostgreSQL の pg_buffercache に当たる）
--     INNODB_BUFFER_PAGE はバッファプール全体をなめるので、本番の大きなサーバーでは重い
SELECT TABLE_NAME, INDEX_NAME, COUNT(*) AS pages, ROUND(SUM(DATA_SIZE) / 1024 / 1024, 1) AS data_mb
FROM information_schema.INNODB_BUFFER_PAGE
WHERE TABLE_NAME LIKE CONCAT('`', DATABASE(), '`.%')
GROUP BY TABLE_NAME, INDEX_NAME
ORDER BY pages DESC
LIMIT 10;

-- (5) old 側に入ったまま young 側へ昇格しなかったページの累計（大きな全件読みがよく使うページを追い出さない仕組み）
SELECT PAGES_MADE_YOUNG, PAGES_NOT_MADE_YOUNG, HIT_RATE
FROM information_schema.INNODB_BUFFER_POOL_STATS;

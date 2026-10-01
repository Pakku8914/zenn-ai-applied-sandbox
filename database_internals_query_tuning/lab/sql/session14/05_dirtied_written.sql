-- S14-05 EXPLAIN (BUFFERS) の dirtied と written を読む
-- \i sql/session14/05_dirtied_written.sql（後半で 200 万行を 2 回入れるので 10 秒ほどかかる）
--   hit     … 共有バッファに載っていたページ
--   read    … 共有バッファに無く、OS から読んだページ（OS のキャッシュにあればディスクには行かない）
--   dirtied … この文が「きれいな」ページを変更して、ダーティ（データファイルへの書き戻しが必要）にした数
--   written … この文が自分でデータファイルへ書き出したページの数
SET max_parallel_workers_per_gather = 0;
SET client_min_messages = warning;
DROP TABLE IF EXISTS s14_t, s14_big, s14_big2;
RESET client_min_messages;
CREATE TABLE s14_t (LIKE orders) WITH (autovacuum_enabled = off);
INSERT INTO s14_t SELECT * FROM orders WHERE id <= 100000 ORDER BY id;

-- (1) 投入直後の SELECT：dirtied は出ない。投入したページはまだデータファイルに書かれておらず、すでにダーティだから
--     （行に「コミット済み」の印＝ヒントビットを付けてはいるが、dirtied は「きれい→ダーティ」に変えた数だけを数える）
EXPLAIN (ANALYZE, BUFFERS) SELECT count(*) FROM s14_t;

-- (2) 作り直して、チェックポイントでページをきれいにしてから読む：1 回目は全ページで dirtied、2 回目は出ない
TRUNCATE s14_t;
INSERT INTO s14_t SELECT * FROM orders WHERE id <= 100000 ORDER BY id;
CHECKPOINT;
EXPLAIN (ANALYZE, BUFFERS) SELECT count(*) FROM s14_t;
EXPLAIN (ANALYZE, BUFFERS) SELECT count(*) FROM s14_t;

-- (3) UPDATE（先頭の 1 万行）→ チェックポイント → SELECT：古い版と新しい版に印を付けるページが dirtied になる
UPDATE s14_t SET status = status WHERE id <= 10000;
CHECKPOINT;
EXPLAIN (ANALYZE, BUFFERS) SELECT count(*) FROM s14_t;

-- (4) 200 万行の INSERT：written はテーブルの末尾に新しいページを足すとき（ファイルの拡張）の書き込みも数える
--     (6) で「だれがデータファイルへ書いたか」を見るため、サーバー全体の I/O 統計（pg_stat_io）をここで 0 に戻す
SELECT pg_stat_force_next_flush();
SELECT pg_stat_reset_shared('io');
CREATE TABLE s14_big (LIKE order_items) WITH (autovacuum_enabled = off);
CREATE TABLE s14_big2 (LIKE order_items) WITH (autovacuum_enabled = off);
EXPLAIN (ANALYZE, BUFFERS, COSTS OFF) INSERT INTO s14_big SELECT * FROM order_items;
EXPLAIN (ANALYZE, BUFFERS, COSTS OFF) INSERT INTO s14_big2 SELECT * FROM order_items;
-- 共有バッファはほぼダーティなページで埋まっている
SELECT buffers_used, buffers_unused, buffers_dirty FROM pg_buffercache_summary();

-- (5) その状態で order_items を主キーの順に 100 万行読む：空き枠を作るため、SELECT がダーティなページを自分で書き出す（written）
SET enable_seqscan = off;
SET enable_bitmapscan = off;
EXPLAIN (ANALYZE, BUFFERS, COSTS OFF) SELECT sum(quantity) FROM order_items WHERE id <= 1000000;
RESET enable_seqscan;
RESET enable_bitmapscan;

-- (6) 残りのダーティページはチェックポイントが書き出す。(4) からの書き込みを、書いたプロセスの種類ごとに見る
--     client backend … SQL を実行した接続自身 / background writer … 空き枠を先回りして作る / checkpointer … チェックポイント
--     context の normal は普通の読み書き、bulkread / bulkwrite はリングバッファを使った大きな読み書き
CHECKPOINT;
-- この接続の I/O 統計はまだ反映されていないことがあるので、反映させてから見る
SELECT pg_stat_force_next_flush();
SELECT backend_type, context, writes, extends, evictions
FROM pg_stat_io
WHERE object = 'relation' AND backend_type IN ('client backend', 'background writer', 'checkpointer')
  AND (writes > 0 OR extends > 0 OR evictions > 0)
ORDER BY backend_type, context;
RESET max_parallel_workers_per_gather;

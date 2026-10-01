-- R03-07 ジョブキューの設計：部分インデックス + FOR UPDATE SKIP LOCKED
-- \i sql/review03/07_queue_partial_index.sql（数秒で終わる）
-- 10 万件のジョブのうち、未処理（queued）は 100 件だけという、よくある偏り
SET client_min_messages = warning;
DROP TABLE IF EXISTS r03_jobs;
RESET client_min_messages;
CREATE TABLE r03_jobs (id integer PRIMARY KEY, status text NOT NULL, payload text NOT NULL);
INSERT INTO r03_jobs
SELECT g, CASE WHEN g > 99900 THEN 'queued' ELSE 'done' END, 'job-' || g
FROM generate_series(1, 100000) AS g;
VACUUM (ANALYZE) r03_jobs;

-- (1) インデックスが主キーだけ：主キーの順に読みながら queued を探す（処理済みの 99,900 行を読み飛ばす）
EXPLAIN (ANALYZE, BUFFERS)
SELECT id FROM r03_jobs WHERE status = 'queued' ORDER BY id LIMIT 1 FOR UPDATE SKIP LOCKED;

-- (2) 未処理の行だけを持つ部分インデックス
CREATE INDEX r03_jobs_queued_idx ON r03_jobs (id) WHERE status = 'queued';
EXPLAIN (ANALYZE, BUFFERS)
SELECT id FROM r03_jobs WHERE status = 'queued' ORDER BY id LIMIT 1 FOR UPDATE SKIP LOCKED;

-- (3) 大きさの比較：全行の status インデックスと、部分インデックス
CREATE INDEX r03_jobs_status_idx ON r03_jobs (status);
SELECT indexrelid::regclass AS index, pg_size_pretty(pg_relation_size(indexrelid)) AS size,
       pg_relation_size(indexrelid) / 8192 AS pages
FROM pg_index WHERE indrelid = 'r03_jobs'::regclass ORDER BY pages DESC;

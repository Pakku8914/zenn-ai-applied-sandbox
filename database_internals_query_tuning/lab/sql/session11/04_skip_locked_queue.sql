-- S11-04 SKIP LOCKED：ジョブキューで「他の人が取ったジョブは飛ばして次を取る」
-- 【2セッション】見出しごとに、書かれた側のセッションに貼る。後半（SKIP LOCKED なし）でセッションBが止まり、セッションAの COMMIT で進む。

-- [A1] セッションA: 作業用テーブルを作り直し、ワーカーAが未処理のジョブを 1 件取る
\i sql/session11/00_setup.sql
BEGIN;
SELECT id FROM s11_jobs WHERE status = 'queued' ORDER BY id LIMIT 1 FOR UPDATE SKIP LOCKED;

-- [B1] セッションB: ワーカーBも同時に 1 件取る。ロックされている 1 は飛ばして 2 を取る（待たない）
BEGIN;
SELECT id FROM s11_jobs WHERE status = 'queued' ORDER BY id LIMIT 1 FOR UPDATE SKIP LOCKED;

-- [A2] セッションA: ジョブ1を処理済みにしてコミット
UPDATE s11_jobs SET status = 'done', worker = 'A' WHERE id = 1;
COMMIT;

-- [B2] セッションB: ジョブ2を処理済みにしてコミット
UPDATE s11_jobs SET status = 'done', worker = 'B' WHERE id = 2;
COMMIT;

-- [A3] セッションA: 次のジョブ（3）を取って処理中にする
BEGIN;
SELECT id FROM s11_jobs WHERE status = 'queued' ORDER BY id LIMIT 1 FOR UPDATE SKIP LOCKED;

-- [B3] セッションB: SKIP LOCKED を付けないと、ジョブ3のロックを待つ（ここで止まる）
BEGIN;
SELECT id FROM s11_jobs WHERE status = 'queued' ORDER BY id LIMIT 1 FOR UPDATE;

-- [A4] セッションA: ジョブ3を処理済みにしてコミットする。セッションBは、待っていた行が条件（queued）に合わなくなったので次の 4 を返す
UPDATE s11_jobs SET status = 'done', worker = 'A' WHERE id = 3;
COMMIT;

-- [B4] セッションB: ジョブ4を処理済みにしてコミット
UPDATE s11_jobs SET status = 'done', worker = 'B' WHERE id = 4;
COMMIT;
SELECT id, status, worker FROM s11_jobs WHERE status = 'done' ORDER BY id;

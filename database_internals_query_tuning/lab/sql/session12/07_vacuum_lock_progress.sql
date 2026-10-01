-- S12-07 普通の VACUUM は読み書きを止めない（SHARE UPDATE EXCLUSIVE）。進み具合は pg_stat_progress_vacuum で見る
-- 【3セッション】見出しごとに、書かれた側に貼る。06 までを実行したあとの s12_orders を使う。
-- セッションAの VACUUM は、わざと遅くしてあるので終わらない。最後にセッションAで Ctrl+C を押して止める。
-- vacuum_cost_delay / vacuum_cost_limit は「一定量の仕事をしたら休む」設定。autovacuum は既定で 2ms 休む（cost_limit 200）

-- [A1] セッションA: 20万行を更新して不要行を作り、100ms 休みながら少しずつ進む VACUUM を始める（ここで止まる。VACUUM が走り続ける）
UPDATE s12_orders SET status = status WHERE id <= 200000;
SET track_cost_delay_timing = on;
SET vacuum_cost_delay = '100ms';
SET vacuum_cost_limit = 10;
VACUUM s12_orders;

-- [C1] セッションC: VACUUM が持っているロックと進み具合
SELECT l.pid, l.mode, l.granted FROM pg_locks AS l JOIN pg_stat_activity AS a USING (pid)
WHERE l.locktype = 'relation' AND l.relation = 's12_orders'::regclass AND a.backend_type = 'client backend';
SELECT pid, phase, heap_blks_total, heap_blks_scanned, heap_blks_vacuumed, dead_tuple_bytes, delay_time
FROM pg_stat_progress_vacuum WHERE relid = 's12_orders'::regclass;

-- [B1] セッションB: VACUUM の最中でも、読むのも書くのも待たない
SELECT count(*) FROM s12_orders WHERE id <= 10;
UPDATE s12_orders SET status = status WHERE id = 1;

-- [C2] セッションC: 5秒待って、もう一度進み具合を見る（少ししか進んでいない）
SELECT pid, phase, heap_blks_total, heap_blks_scanned, heap_blks_vacuumed, dead_tuple_bytes, delay_time
FROM pg_stat_progress_vacuum WHERE relid = 's12_orders'::regclass;

-- [A2] セッションA: Ctrl+C を押して VACUUM を止める（途中まで回収した分は無駄にならない）

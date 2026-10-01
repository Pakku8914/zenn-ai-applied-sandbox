-- S12-11 凍結（freeze）：トランザクション番号の周回に備えて、古い行の xmin を「凍結済み」にする
-- 1つのセッションで上から順に実行してよい: \i sql/session12/11_freeze.sql（01 か 10 で s12_orders を作ったあと）
-- age() の値は、サーバー全体でこれまでに使われたトランザクション番号の数で決まるので、環境ごとに違う

-- autovacuum に先回りされないよう、このテーブルの自動 VACUUM を止めておく
ALTER TABLE s12_orders SET (autovacuum_enabled = off);

-- (1) 周回を防ぐための設定。autovacuum_freeze_max_age（2億）を超えたテーブルは、autovacuum が強制的に凍結しに来る
SHOW autovacuum_freeze_max_age;
SHOW vacuum_freeze_min_age;
SHOW vacuum_failsafe_age;

-- (2) トランザクション番号は 32 ビット。比較できるのは前後 2^31（約21億）までなので、それより古い番号は「未来」に見えてしまう
SELECT 2^31 AS xid_half_space, (2^31)::bigint - current_setting('autovacuum_freeze_max_age')::bigint AS margin_after_forced_vacuum;

-- (3) テーブルごとの「まだ凍結していない最も古い番号」とその年齢、データベース全体の年齢
SELECT relname, relfrozenxid, age(relfrozenxid) FROM pg_class WHERE relname IN ('orders', 's12_orders') ORDER BY relname;
SELECT age(datfrozenxid) AS db_age, (2^31)::bigint - age(datfrozenxid) AS xids_left FROM pg_database WHERE datname = current_database();

-- (4) 1万行を更新して新しい版を作り、凍結前の状態を見る（HEAP_XMIN_FROZEN なし）。
--     凍結は HEAP_XMIN_COMMITTED と HEAP_XMIN_INVALID の 2 ビットを両方立てた状態で表す（combined_flags に HEAP_XMIN_FROZEN と出る）
UPDATE s12_orders SET status = status WHERE id <= 10000;
SELECT count(*) FILTER (WHERE 'HEAP_XMIN_FROZEN' = ANY (f.combined_flags)) AS frozen,
       count(*) FILTER (WHERE NOT 'HEAP_XMIN_FROZEN' = ANY (f.combined_flags)) AS not_frozen
FROM s12_orders AS o,
     LATERAL (SELECT (ctid::text::point)[0]::int AS blk, (ctid::text::point)[1]::int AS lp) AS p,
     LATERAL (SELECT h.t_infomask, h.t_infomask2 FROM heap_page_items(get_raw_page('s12_orders', p.blk)) AS h WHERE h.lp = p.lp) AS h,
     LATERAL heap_tuple_infomask_flags(h.t_infomask, h.t_infomask2) AS f
WHERE o.id <= 3;

-- (5) VACUUM (FREEZE) で全ページを凍結する
VACUUM (FREEZE, VERBOSE) s12_orders;
SELECT relname, relfrozenxid, age(relfrozenxid) FROM pg_class WHERE relname = 's12_orders';
SELECT o.id, f.raw_flags, f.combined_flags
FROM s12_orders AS o,
     LATERAL (SELECT (ctid::text::point)[0]::int AS blk, (ctid::text::point)[1]::int AS lp) AS p,
     LATERAL (SELECT h.t_infomask, h.t_infomask2 FROM heap_page_items(get_raw_page('s12_orders', p.blk)) AS h WHERE h.lp = p.lp) AS h,
     LATERAL heap_tuple_infomask_flags(h.t_infomask, h.t_infomask2) AS f
WHERE o.id <= 3 ORDER BY o.id;

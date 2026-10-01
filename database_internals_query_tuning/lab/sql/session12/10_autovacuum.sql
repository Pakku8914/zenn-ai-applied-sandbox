-- S12-10 autovacuum はいつ走るか。そして、長時間トランザクションがあると走っても回収できない
-- 【2セッション】見出しごとに、書かれた側に貼る。「N秒待って」とある手順は、その秒数だけ待ってから貼る。どこでも止まらない。
-- 統計（n_dead_tup など）を出発点からにするため、最初に s12_orders を作り直す（01 と同じ手順。数秒で終わる）。
-- 自動の VACUUM の記録をサーバーログに残すため、このテーブルだけ log_autovacuum_min_duration = 0 にする
-- （ログは別のターミナルで docker compose logs pg | grep 's12_orders' で見る）

-- [A1] セッションA: s12_orders を作り直してから発火点を計算する。VACUUM は 50 + 0.2 × 100万 = 200,050 行、ANALYZE は 50 + 0.1 × 100万 = 100,050 行
DROP TABLE IF EXISTS s12_orders;
CREATE TABLE s12_orders (LIKE orders) WITH (autovacuum_enabled = off);
INSERT INTO s12_orders SELECT * FROM orders ORDER BY id;
-- INSERT の件数を統計に反映させてから VACUUM する（反映が VACUUM の後になると「VACUUM 後の INSERT」と数えられ、
-- 挿入が多いテーブル向けの自動の VACUUM が余分に走る）
SELECT pg_stat_force_next_flush();
ALTER TABLE s12_orders ADD PRIMARY KEY (id);
VACUUM (ANALYZE) s12_orders;
\i sql/session12/09_autovacuum_status.sql
SELECT c.reltuples::bigint AS reltuples,
       current_setting('autovacuum_vacuum_threshold')::int
         + current_setting('autovacuum_vacuum_scale_factor')::float8 * c.reltuples AS vacuum_trigger,
       current_setting('autovacuum_analyze_threshold')::int
         + current_setting('autovacuum_analyze_scale_factor')::float8 * c.reltuples AS analyze_trigger
FROM pg_class AS c WHERE c.relname = 's12_orders';
SHOW autovacuum_naptime;
ALTER TABLE s12_orders SET (autovacuum_enabled = on, log_autovacuum_min_duration = 0);
UPDATE s12_orders SET status = status WHERE id <= 199000;
-- 統計はトランザクションの終わりから少し遅れて反映される。すぐに見るときは反映を促してから見る
SELECT pg_stat_force_next_flush();
\i sql/session12/09_autovacuum_status.sql

-- [A2] セッションA: 30秒待って状態を見る。ANALYZE の発火点は超えたので自動 ANALYZE は走るが、VACUUM は走らない
\i sql/session12/09_autovacuum_status.sql

-- [A3] セッションA: あと 3,000 行更新して、不要行を VACUUM の発火点（200,050）より多くする
UPDATE s12_orders SET status = status WHERE id > 199000 AND id <= 202000;
SELECT pg_stat_force_next_flush();
\i sql/session12/09_autovacuum_status.sql

-- [A4] セッションA: 30秒待って状態を見る。自動の VACUUM が走り、不要行が 0 になる
\i sql/session12/09_autovacuum_status.sql

-- [A5] セッションA: テーブル単位の設定で発火点を下げる（比率 0・固定 10,000 行）
ALTER TABLE s12_orders SET (autovacuum_vacuum_scale_factor = 0, autovacuum_vacuum_threshold = 10000);

-- [B1] セッションB: Repeatable Read のトランザクションを開いたままにする（古い版を必要とし続ける）
BEGIN ISOLATION LEVEL REPEATABLE READ;
SELECT count(*) FROM s12_orders WHERE id <= 10;

-- [A6] セッションA: 2 万行を更新する（発火点 10,000 を超える）
UPDATE s12_orders SET status = status WHERE id <= 20000;
SELECT pg_stat_force_next_flush();
\i sql/session12/09_autovacuum_status.sql

-- [A7] セッションA: 40秒待って状態を見る。自動の VACUUM は何度も走る（av_count が増える）のに、不要行は減らない
\i sql/session12/09_autovacuum_status.sql

-- [B2] セッションB: トランザクションを閉じる
COMMIT;

-- [A8] セッションA: 30秒待って状態を見る。次の自動の VACUUM で回収される
\i sql/session12/09_autovacuum_status.sql

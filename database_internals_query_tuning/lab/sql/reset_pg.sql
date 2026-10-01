-- 章の実験で追加したものを片付け、「主キーと外部キー制約だけ」の出発点に戻す。
-- データ（4テーブルの行）には触れないので数秒で終わる。データごと戻したいときは tools/seed.sh を使う。
-- 使い方: docker compose exec lab psql -f sql/reset_pg.sql

-- 制約に紐づかないインデックス（章で CREATE INDEX したもの）を消す
DO $$
DECLARE r record;
BEGIN
  FOR r IN
    SELECT i.indexrelid::regclass AS idx
    FROM pg_index i
    JOIN pg_class t ON t.oid = i.indrelid
    JOIN pg_namespace n ON n.oid = t.relnamespace
    WHERE n.nspname = 'public'
      AND t.relname IN ('customers', 'products', 'orders', 'order_items')
      AND NOT EXISTS (SELECT 1 FROM pg_constraint c WHERE c.conindid = i.indexrelid)
  LOOP
    EXECUTE format('DROP INDEX %s', r.idx);
  END LOOP;
END $$;

-- 拡張統計（CREATE STATISTICS）を消す
DO $$
DECLARE r record;
BEGIN
  FOR r IN SELECT format('%I.%I', stxnamespace::regnamespace, stxname) AS st FROM pg_statistic_ext
           WHERE stxnamespace = 'public'::regnamespace
  LOOP
    EXECUTE format('DROP STATISTICS %s', r.st);
  END LOOP;
END $$;

-- 章が作った作業用のテーブル・ビュー（4テーブル以外）を消す
DO $$
DECLARE r record;
BEGIN
  FOR r IN SELECT c.oid::regclass AS rel, c.relkind
           FROM pg_class c
           WHERE c.relnamespace = 'public'::regnamespace
             AND c.relkind IN ('r', 'p', 'v', 'm')
             AND c.relname NOT IN ('customers', 'products', 'orders', 'order_items')
             AND NOT c.relispartition
             AND NOT EXISTS (SELECT 1 FROM pg_depend d
                             WHERE d.objid = c.oid AND d.deptype = 'e')
  LOOP
    EXECUTE format('DROP %s IF EXISTS %s CASCADE',
                   CASE r.relkind WHEN 'v' THEN 'VIEW'
                                  WHEN 'm' THEN 'MATERIALIZED VIEW'
                                  ELSE 'TABLE' END,
                   r.rel);
  END LOOP;
END $$;

-- 列ごとの統計の目標値（ALTER TABLE ... SET STATISTICS）とテーブルのオプション（autovacuum_enabled など）を戻す
DO $$
DECLARE r record; k text;
BEGIN
  FOR r IN
    SELECT a.attrelid::regclass AS rel, a.attname
    FROM pg_attribute a JOIN pg_class c ON c.oid = a.attrelid
    WHERE c.relnamespace = 'public'::regnamespace
      AND c.relname IN ('customers', 'products', 'orders', 'order_items')
      AND a.attnum > 0 AND NOT a.attisdropped AND a.attstattarget IS NOT NULL
  LOOP
    EXECUTE format('ALTER TABLE %s ALTER COLUMN %I SET STATISTICS DEFAULT', r.rel, r.attname);
  END LOOP;
  FOR r IN
    SELECT c.oid::regclass AS rel, c.reloptions
    FROM pg_class c
    WHERE c.relnamespace = 'public'::regnamespace
      AND c.relname IN ('customers', 'products', 'orders', 'order_items')
      AND c.reloptions IS NOT NULL
  LOOP
    FOREACH k IN ARRAY r.reloptions LOOP
      EXECUTE format('ALTER TABLE %s RESET (%s)', r.rel, split_part(k, '=', 1));
    END LOOP;
  END LOOP;
END $$;

-- 不要行を回収して Visibility Map を立て直し、統計を取り直す。
-- ROLLBACK した更新も不要行と Visibility Map のビット落ちを残すため、ANALYZE だけでは出発点に戻らない
-- 不要行が少ないとインデックスの掃除が省略され Index Only Scan の Heap Fetches が 0 に戻らないため、INDEX_CLEANUP ON を付ける
VACUUM (ANALYZE, INDEX_CLEANUP ON) customers, products, orders, order_items;

-- 章で ALTER SYSTEM した設定を戻す（docker-compose.yml の -c で渡した学習用の設定はそのまま残る）
ALTER SYSTEM RESET ALL;
SELECT pg_reload_conf() AS reloaded \gset

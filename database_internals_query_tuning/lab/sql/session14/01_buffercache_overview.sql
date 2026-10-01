-- S14-01 共有バッファ（shared_buffers）の中身を pg_buffercache で覗く
-- \i sql/session14/01_buffercache_overview.sql
CREATE EXTENSION IF NOT EXISTS pg_buffercache;
SHOW shared_buffers;
-- 共有バッファは 8KB のページを入れる枠（バッファ）の並び。256MB ÷ 8KB = 32768 枠
SELECT setting::int AS buffers, pg_size_pretty(setting::bigint * 8192) AS size
FROM pg_settings WHERE name = 'shared_buffers';
-- 使用中・未使用・ダーティ（変更されてまだデータファイルに書かれていない）枠の数と、使用回数（usagecount）の平均
SELECT * FROM pg_buffercache_summary();
-- このデータベースのどのテーブル・インデックスが何ページ載っているか（上位 10）
--   cached_pct … そのリレーションの全ページのうち、共有バッファに載っている割合
SELECT c.relname, c.relkind, count(*) AS buffers, pg_size_pretty(count(*) * 8192) AS cached,
       pg_relation_size(c.oid) / 8192 AS rel_pages,
       round(100.0 * count(*) / nullif(pg_relation_size(c.oid) / 8192, 0), 1) AS cached_pct
FROM pg_buffercache b
JOIN pg_class c ON b.relfilenode = pg_relation_filenode(c.oid)
WHERE b.reldatabase = (SELECT oid FROM pg_database WHERE datname = current_database())
  AND c.relnamespace = 'public'::regnamespace
GROUP BY c.oid, c.relname, c.relkind
ORDER BY buffers DESC
LIMIT 10;

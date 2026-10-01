-- S12-02 s12_orders の肥大化を測る（何度でも実行してよい。1 秒ほどかかる）
-- heap_pages / heap_size   : テーブル本体のページ数と大きさ（pg_relation_size）
-- dead_pct / free_pct      : 不要行が占める割合と、空き領域の割合（pgstattuple。全ページを読む）
-- pkey_size / leaf_density : 主キーのインデックスの大きさと、リーフページの詰まり具合（pgstatindex）
SELECT pg_relation_size('s12_orders') / 8192 AS heap_pages,
       pg_size_pretty(pg_relation_size('s12_orders')) AS heap_size,
       t.tuple_count AS live, t.dead_tuple_count AS dead,
       t.dead_tuple_percent AS dead_pct, t.free_percent AS free_pct,
       pg_size_pretty(pg_relation_size('s12_orders_pkey')) AS pkey_size,
       i.leaf_pages, i.avg_leaf_density AS leaf_density
FROM pgstattuple('s12_orders') AS t, pgstatindex('s12_orders_pkey') AS i;

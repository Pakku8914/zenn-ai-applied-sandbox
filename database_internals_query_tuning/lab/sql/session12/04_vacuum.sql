-- S12-04 VACUUM：不要行を回収して「空き」にする。ファイルは小さくならない
-- \i sql/session12/04_vacuum.sql
\timing on
VACUUM (VERBOSE) s12_orders;
\timing off
-- dead は 0 になるが heap_pages はそのまま。空き（free_pct）が約半分になり、インデックスのリーフも半分ほどに薄まる
\i sql/session12/02_measure.sql

-- S15-12 PostgreSQL：A が COMMIT した後の VACUUM（どちらの端末でもよい）
VACUUM (VERBOSE) s15_mvcc;
SELECT pg_relation_size('s15_mvcc') / 8192 AS pages;
EXPLAIN (ANALYZE, BUFFERS) SELECT sum(v) FROM s15_mvcc;

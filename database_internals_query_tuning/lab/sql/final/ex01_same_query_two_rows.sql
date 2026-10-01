-- Final-ex01 pg_stat_statements に「同じ SQL」が 2 行に分かれて出る理由：パラメータの型が違うと別のクエリとして数えられる
-- アプリのドライバー（Python の psycopg など）は、整数を値の大きさで smallint / integer に送り分けることがある。
-- ここでは psql の PREPARE で、同じ SELECT を 3 通りに準備して再現する（a と b は型が同じで名前だけ違う、c は型が違う）
-- workload.py の統計とは本文（PREPARE final_ex01_...）が違うので混ざらない
PREPARE final_ex01_a(integer)  AS SELECT count(*) FROM orders WHERE customer_id = $1;
PREPARE final_ex01_b(integer)  AS SELECT count(*) FROM orders WHERE customer_id = $1;
PREPARE final_ex01_c(smallint) AS SELECT count(*) FROM orders WHERE customer_id = $1;
EXECUTE final_ex01_a(40000);
EXECUTE final_ex01_b(45000);
EXECUTE final_ex01_c(12345);

-- queryid（クエリの形から計算する識別子）は a と b で同じ、c だけ別。本文（query）は最初に見た a のものが表示される
SELECT queryid, calls, regexp_replace(query, '\s+', ' ', 'g') AS query
FROM pg_stat_statements
WHERE dbid = (SELECT oid FROM pg_database WHERE datname = current_database())
  AND query LIKE 'PREPARE final_ex01%'
ORDER BY calls DESC;
DEALLOCATE final_ex01_a;
DEALLOCATE final_ex01_b;
DEALLOCATE final_ex01_c;

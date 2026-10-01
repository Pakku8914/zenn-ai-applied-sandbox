"""S16 パーティションとスケールの選択肢 — 自己検証。

出発点（tools/reset.sh 直後）から単独で実行する。作業用テーブル（s16_ 接頭辞）を自分で作る。
判定に使うのは、計画に現れるパーティション・Subplans Removed・エラーメッセージ・件数・不要行・WAL のレコード数と、
10 倍以上の差がある時間の大小だけ。MySQL は計画（partitions 列）とエラーだけを確かめ、行は入れない。
"""

from __future__ import annotations

import statistics
import time

import psycopg

from labcheck import check, explain, finish, mysql_connect, pg_connect, walk

JUNE = "ordered_at >= '2025-06-01' AND ordered_at < '2025-07-01'"


def scanned(plan: dict) -> list[str]:
    root = plan.get("Plan", plan)
    return sorted(n["Relation Name"] for n in walk(root) if "Relation Name" in n)


def subplans_removed(plan: dict) -> int:
    return sum(n.get("Subplans Removed", 0) for n in walk(plan.get("Plan", plan)))


def error_of(cur, sql: str) -> str:
    try:
        cur.execute(sql)
    except psycopg.Error as e:
        return str(e)
    return ""


def create_range_partitions(cur, name: str) -> None:
    cur.execute(f"DROP TABLE IF EXISTS {name}")
    cur.execute(f"CREATE TABLE {name} (id bigint NOT NULL, customer_id integer NOT NULL, "
                "ordered_at timestamptz NOT NULL, status text NOT NULL) PARTITION BY RANGE (ordered_at)")
    for m in range(1, 13):
        to = "2026-01-01" if m == 12 else f"2025-{m + 1:02d}-01"
        cur.execute(f"CREATE TABLE {name}_2025_{m:02d} PARTITION OF {name} "
                    f"FOR VALUES FROM ('2025-{m:02d}-01') TO ('{to}')")
    cur.execute(f"INSERT INTO {name} SELECT id, customer_id, ordered_at, status FROM orders")
    cur.execute(f"VACUUM ANALYZE {name}")


def backend_wal_records(cur) -> int:
    cur.execute("SELECT pg_stat_force_next_flush()")
    cur.execute("SELECT 1")
    cur.execute("SELECT wal_records FROM pg_stat_get_backend_wal(pg_backend_pid())")
    return int(cur.fetchone()[0])


def check_partitions(cur) -> None:
    create_range_partitions(cur, "s16_orders")
    cur.execute("SELECT count(DISTINCT tableoid), count(*) FROM s16_orders")
    check("月次レンジ：12 個のパーティションに 100 万行", cur.fetchone() == (12, 1000000))

    plan = explain(cur, f"SELECT count(*) FROM s16_orders WHERE {JUNE}")
    check("パーティションキーの範囲条件は6月だけを読む", scanned(plan) == ["s16_orders_2025_06"], str(scanned(plan)))
    for label, cond in (("date_trunc をかける", "date_trunc('month', ordered_at) = '2025-06-01'"),
                        ("::date に変換する", "ordered_at::date BETWEEN '2025-06-01' AND '2025-06-30'"),
                        ("パーティションキー以外の条件だけ", "status = 'cancelled'")):
        plan = explain(cur, f"SELECT count(*) FROM s16_orders WHERE {cond}")
        check(f"{label}と12個すべてを読む", len(scanned(plan)) == 12, str(len(scanned(plan))))
    cur.execute("SELECT (SELECT count(*) FROM s16_orders WHERE " + JUNE + "), "
                "(SELECT count(*) FROM s16_orders WHERE date_trunc('month', ordered_at) = '2025-06-01')")
    check("書き方が違っても6月の件数は同じ 82,200", cur.fetchone() == (82200, 82200))

    # 実行時のプルーニング
    cur.execute("PREPARE s16_range(timestamptz, timestamptz) AS "
                "SELECT count(*) FROM s16_orders WHERE ordered_at >= $1 AND ordered_at < $2")
    cur.execute("SET plan_cache_mode = force_generic_plan")
    plan = explain(cur, "EXECUTE s16_range('2025-06-01', '2025-07-01')")
    check("汎用プランでは実行開始時に 11 個が外れる（Subplans Removed: 11）",
          subplans_removed(plan) == 11, str(subplans_removed(plan)))
    cur.execute("SET plan_cache_mode = auto")
    plan = explain(cur, "EXECUTE s16_range('2025-06-01', '2025-07-01')")
    check("専用プランでは計画の時点で6月だけ（Subplans Removed なし）",
          scanned(plan) == ["s16_orders_2025_06"] and subplans_removed(plan) == 0)
    cur.execute("DEALLOCATE s16_range")
    cur.execute("RESET plan_cache_mode")
    plan = explain(cur, "SELECT count(*) FROM s16_orders WHERE ordered_at >= DATE '2025-06-01' "
                        "AND ordered_at < DATE '2025-07-01'")
    check("date 型の値と比べると、実行開始時に 11 個が外れる", subplans_removed(plan) == 11, str(subplans_removed(plan)))

    # DEFAULT パーティション
    err = error_of(cur, "INSERT INTO s16_orders VALUES (1000001, 1, '2026-01-15 12:00:00+00', 'pending')")
    check("範囲外の行は DEFAULT が無いとエラー", "no partition of relation" in err, err.splitlines()[0] if err else "")
    cur.execute("CREATE TABLE s16_orders_default PARTITION OF s16_orders DEFAULT")
    cur.execute("INSERT INTO s16_orders VALUES (1000001, 1, '2026-01-15 12:00:00+00', 'pending')")
    plan = explain(cur, "SELECT count(*) FROM s16_orders WHERE ordered_at >= '2025-12-15' AND ordered_at < '2026-01-15'")
    check("12月後半〜1月の検索は 12月と DEFAULT を読む",
          scanned(plan) == ["s16_orders_2025_12", "s16_orders_default"], str(scanned(plan)))
    err = error_of(cur, "CREATE TABLE s16_orders_2026_01 PARTITION OF s16_orders "
                        "FOR VALUES FROM ('2026-01-01') TO ('2026-02-01')")
    check("DEFAULT にその範囲の行があると新しいパーティションを作れない", "would be violated by some row" in err)
    err = error_of(cur, "ALTER TABLE s16_orders DETACH PARTITION s16_orders_2025_01 CONCURRENTLY")
    check("DEFAULT があると DETACH ... CONCURRENTLY は使えない",
          "cannot detach partitions concurrently when a default partition exists" in err)
    cur.execute("DROP TABLE s16_orders_default")

    # 主キー・一意制約
    err = error_of(cur, "ALTER TABLE s16_orders ADD PRIMARY KEY (id)")
    check("id だけの主キーは作れない", "must include all partitioning columns" in err, err.splitlines()[0] if err else "")
    cur.execute("ALTER TABLE s16_orders ADD PRIMARY KEY (id, ordered_at)")
    cur.execute("BEGIN")
    cur.execute("INSERT INTO s16_orders SELECT id, customer_id, ordered_at + interval '1 month', status "
                "FROM s16_orders WHERE id = 500000")
    cur.execute("SELECT count(*) FROM s16_orders WHERE id = 500000")
    dup = cur.fetchone()[0]
    cur.execute("ROLLBACK")
    check("(id, ordered_at) の主キーでは、別の月なら同じ id が入る", dup == 2, str(dup))
    plan = explain(cur, "SELECT * FROM s16_orders WHERE id = 500000")
    check("id だけで引くと 12 個すべてのパーティションを探す", len(scanned(plan)) == 12, str(len(scanned(plan))))

    # DELETE と DETACH / DROP
    cur.execute("DROP TABLE IF EXISTS s16_orders_flat")
    cur.execute("CREATE TABLE s16_orders_flat AS SELECT * FROM orders")
    cur.execute("VACUUM ANALYZE s16_orders_flat")
    cur.execute("EXPLAIN (ANALYZE, WAL, FORMAT JSON) "
                "DELETE FROM s16_orders_flat WHERE ordered_at >= '2025-01-01' AND ordered_at < '2025-02-01'")
    wal_delete = cur.fetchone()[0][0]["Plan"]["WAL Records"]
    check("DELETE は1行ごとに WAL を書く（レコード数が削除行数以上）", wal_delete >= 84939, str(wal_delete))
    cur.execute("SELECT dead_tuple_count FROM pgstattuple('s16_orders_flat')")
    dead = cur.fetchone()[0]
    check("DELETE は1月の 84,939 行を不要行として残す", dead == 84939, str(dead))
    w0 = backend_wal_records(cur)
    cur.execute("ALTER TABLE s16_orders DETACH PARTITION s16_orders_2025_01 CONCURRENTLY")
    cur.execute("DROP TABLE s16_orders_2025_01")
    wal_drop = backend_wal_records(cur) - w0
    cur.execute("SELECT (SELECT count(*) FROM s16_orders), (SELECT count(*) FROM s16_orders_flat)")
    check("DELETE でも DETACH + DROP でも残りは 915,061 行", cur.fetchone() == (915061, 915061))
    check("DETACH + DROP の WAL レコードは DELETE の 100 分の 1 未満",
          wal_drop * 100 < wal_delete, f"DELETE {wal_delete} / DETACH+DROP {wal_drop}")


def check_list_hash(cur) -> None:
    cur.execute("DROP TABLE IF EXISTS s16_orders_by_status, s16_orders_by_customer")
    cur.execute("CREATE TABLE s16_orders_by_status (LIKE orders) PARTITION BY LIST (status)")
    for v in ("completed", "pending", "cancelled"):
        cur.execute(f"CREATE TABLE s16_orders_by_status_{v} PARTITION OF s16_orders_by_status FOR VALUES IN ('{v}')")
    cur.execute("INSERT INTO s16_orders_by_status SELECT * FROM orders")
    cur.execute("VACUUM ANALYZE s16_orders_by_status")
    plan = explain(cur, "SELECT count(*) FROM s16_orders_by_status WHERE status = 'cancelled'")
    check("リスト：status = 'cancelled' は1つだけを読む",
          scanned(plan) == ["s16_orders_by_status_cancelled"], str(scanned(plan)))

    cur.execute("CREATE TABLE s16_orders_by_customer (LIKE orders) PARTITION BY HASH (customer_id)")
    for r in range(4):
        cur.execute(f"CREATE TABLE s16_orders_by_customer_{r} PARTITION OF s16_orders_by_customer "
                    f"FOR VALUES WITH (MODULUS 4, REMAINDER {r})")
    cur.execute("INSERT INTO s16_orders_by_customer SELECT * FROM orders")
    cur.execute("VACUUM ANALYZE s16_orders_by_customer")
    plan = explain(cur, "SELECT count(*) FROM s16_orders_by_customer WHERE customer_id = 777")
    check("ハッシュ：等値条件は1つだけを読む", len(scanned(plan)) == 1, str(scanned(plan)))
    plan = explain(cur, "SELECT count(*) FROM s16_orders_by_customer WHERE customer_id BETWEEN 777 AND 780")
    check("ハッシュ：範囲条件は4つすべてを読む", len(scanned(plan)) == 4, str(scanned(plan)))
    cur.execute("DROP TABLE s16_orders_by_status, s16_orders_by_customer")


def check_connections() -> None:
    n, each, reuse = 100, [], []
    for _ in range(3):
        t = time.perf_counter()
        for i in range(n):
            with psycopg.connect(prepare_threshold=None) as c:
                c.execute("SELECT count(*) FROM customers WHERE id = %s", (i + 1,)).fetchone()
        each.append(time.perf_counter() - t)
        t = time.perf_counter()
        with psycopg.connect(prepare_threshold=None) as c:
            for i in range(n):
                c.execute("SELECT count(*) FROM customers WHERE id = %s", (i + 1,)).fetchone()
        reuse.append(time.perf_counter() - t)
    a, b = statistics.median(each), statistics.median(reuse)
    check("毎回接続する方が、1接続を使い回すより 10 倍以上遅い", a > b * 10, f"約 {a / b:.0f} 倍")


def check_summary(cur) -> None:
    base = ("SELECT (o.ordered_at AT TIME ZONE 'UTC')::date AS day, sum(oi.quantity * oi.unit_price) AS sales, "
            "count(*) AS lines FROM orders o JOIN order_items oi ON oi.order_id = o.id "
            "WHERE o.status <> 'cancelled' GROUP BY day")
    cur.execute("DROP MATERIALIZED VIEW IF EXISTS s16_daily_sales")
    cur.execute("CREATE MATERIALIZED VIEW s16_daily_sales AS " + base)
    cur.execute("SELECT count(*), sum(sales), sum(lines) FROM s16_daily_sales")
    mv = cur.fetchone()
    cur.execute(f"SELECT count(*), sum(sales), sum(lines) FROM ({base}) t")
    check("マテリアライズドビューは 365 日分で、元の集計と同じ合計", mv == cur.fetchone() and mv[0] == 365, str(mv))
    t_base = explain(cur, base + " ORDER BY day")["Execution Time"]
    t_mv = explain(cur, "SELECT day, sales, lines FROM s16_daily_sales ORDER BY day")["Execution Time"]
    check("ビューを読むのは元の集計より 100 倍以上速い", t_mv * 100 < t_base, f"{t_base:.1f} ms → {t_mv:.3f} ms")
    err = error_of(cur, "REFRESH MATERIALIZED VIEW CONCURRENTLY s16_daily_sales")
    check("一意インデックスが無いと REFRESH ... CONCURRENTLY はエラー", "cannot refresh materialized view" in err)
    cur.execute("CREATE UNIQUE INDEX s16_daily_sales_day_idx ON s16_daily_sales (day)")
    cur.execute("REFRESH MATERIALIZED VIEW CONCURRENTLY s16_daily_sales")
    cur.execute("SELECT count(*) FROM s16_daily_sales")
    check("一意インデックスを作ると CONCURRENTLY で作り直せる", cur.fetchone()[0] == 365)

    # 行指向：使う列が1つでも全ページを読む
    q = "SELECT (ordered_at AT TIME ZONE 'UTC')::date AS day, count(*) FROM orders GROUP BY day"
    cur.execute("SET max_parallel_workers_per_gather = 0")
    plan = explain(cur, q, buffers=True)
    seq = [n for n in walk(plan["Plan"]) if n["Node Type"] == "Seq Scan"]
    seq_pages = seq[0]["Shared Hit Blocks"] + seq[0]["Shared Read Blocks"] if seq else 0
    cur.execute("SELECT pg_relation_size('orders') / 8192")
    check("1列だけの集計でも Seq Scan は orders の全ページを読む", seq_pages == cur.fetchone()[0], str(seq_pages))
    est = plan["Plan"]["Plan Rows"]
    cur.execute("CREATE INDEX orders_ordered_at_idx ON orders (ordered_at)")
    cur.execute("VACUUM orders")
    cur.execute("SET enable_seqscan = off")
    plan = explain(cur, q, buffers=True)
    ios = [n for n in walk(plan["Plan"]) if n["Node Type"] == "Index Only Scan"]
    ios_pages = ios[0]["Shared Hit Blocks"] + ios[0]["Shared Read Blocks"] if ios else 0
    check("ordered_at だけのインデックス（細い写し）は読むページが Seq Scan の半分未満",
          bool(ios) and ios_pages * 2 < seq_pages, f"{ios_pages} / {seq_pages}")
    cur.execute("RESET enable_seqscan")
    cur.execute("DROP INDEX orders_ordered_at_idx")

    # 演習：式の統計
    cur.execute("CREATE STATISTICS s16_orders_day_stats ON ((ordered_at AT TIME ZONE 'UTC')::date) FROM orders")
    cur.execute("ANALYZE orders")
    est2 = explain(cur, q)["Plan"]["Plan Rows"]
    check("式の統計を作ると、日数（365）の見積もりが正しくなる", est > 100000 and est2 < 1000, f"{est} → {est2}")
    cur.execute("DROP STATISTICS s16_orders_day_stats")
    cur.execute("ANALYZE orders")
    cur.execute("RESET max_parallel_workers_per_gather")


def check_mysql() -> None:
    my = mysql_connect()
    with my.cursor() as mc:
        mc.execute("DROP TABLE IF EXISTS s16_orders")
        cols = "id BIGINT NOT NULL, customer_id INT NOT NULL, ordered_at DATETIME NOT NULL, status VARCHAR(10) NOT NULL"
        parts = ", ".join(f"PARTITION p2025_{m:02d} VALUES LESS THAN "
                          f"('{'2026-01-01' if m == 12 else f'2025-{m + 1:02d}-01'}')" for m in range(1, 13))
        for label, extra, code in (("主キーにパーティション列が無い", ", PRIMARY KEY (id)", 1503),
                                   ("外部キーを持つ", ", PRIMARY KEY (id, ordered_at), "
                                                     "FOREIGN KEY (customer_id) REFERENCES customers (id)", 1506)):
            try:
                mc.execute(f"CREATE TABLE s16_orders ({cols}{extra}) PARTITION BY RANGE COLUMNS (ordered_at) ({parts})")
                got = 0
            except Exception as e:  # pymysql の例外は args[0] がエラー番号
                got = e.args[0]
            check(f"MySQL: {label}パーティション表は作れない（ERROR {code}）", got == code, str(got))
        mc.execute(f"CREATE TABLE s16_orders ({cols}, PRIMARY KEY (id, ordered_at)) "
                   f"PARTITION BY RANGE COLUMNS (ordered_at) ({parts})")
        mc.execute("EXPLAIN FORMAT=TRADITIONAL SELECT COUNT(*) FROM s16_orders "
                   "WHERE ordered_at >= '2025-06-01' AND ordered_at < '2025-07-01'")
        names = [d[0] for d in mc.description]
        p1 = mc.fetchone()[names.index("partitions")]
        mc.execute("EXPLAIN FORMAT=TRADITIONAL SELECT COUNT(*) FROM s16_orders "
                   "WHERE DATE(ordered_at) BETWEEN '2025-06-01' AND '2025-06-30'")
        p2 = mc.fetchone()[names.index("partitions")]
        check("MySQL: 範囲条件なら partitions 列は p2025_06 だけ", p1 == "p2025_06", str(p1))
        check("MySQL: DATE() をかけると partitions 列に 12 個すべてが並ぶ", len(p2.split(",")) == 12, str(p2))
        mc.execute("DROP TABLE s16_orders")
    my.close()


def main() -> None:
    conn = pg_connect()
    cur = conn.cursor()
    check_partitions(cur)
    cur.execute("DROP TABLE s16_orders, s16_orders_flat")
    check_list_hash(cur)
    check_connections()
    check_summary(cur)
    cur.execute("DROP MATERIALIZED VIEW s16_daily_sales")
    conn.close()
    check_mysql()
    finish("S16 パーティションとスケールの選択肢")


if __name__ == "__main__":
    main()

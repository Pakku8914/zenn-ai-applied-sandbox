"""S06 統計情報とプランナ の自己検証。

出発点（tools/reset.sh 直後）から単独で実行して成功すること。
見積もり rows は ANALYZE の標本抽出で揺れるため、固定値とは比べない。
「同じ統計から手計算した値と一致するか」「実際の行数より桁で小さいか」のように、揺れても結論が変わらない条件だけを使う。
"""

from __future__ import annotations

import time

from labcheck import (actual_total_rows, check, explain, find_nodes, finish,
                      mysql_connect, node_types, pg_connect)

WEEK = "ordered_at >= '2025-06-01' AND ordered_at < '2025-06-08'"
TOKYO_DAY0 = "region = '東京' AND created_at >= '2024-01-01' AND created_at < '2024-01-02'"
TOKYO_DAY0_EQ = "region = '東京' AND created_at = '2024-01-01'"
STALE_JOIN = ("SELECT o.id, c.region FROM s06_orders o JOIN customers c ON c.id = o.customer_id "
              "WHERE o.status = 'returned'")


def est(plan: dict) -> float:
    return plan["Plan"]["Plan Rows"]


def scan_rows_estimate(plan: dict) -> float:
    """並列（Gather）の下の見積もりはワーカーあたりなので、最上位ノードの見積もりを使う。"""
    return plan["Plan"]["Plan Rows"]


def close(a: float, b: float, rel: float = 0.01) -> bool:
    return abs(a - b) <= max(1.0, rel * max(abs(a), abs(b)))


def verify_pg() -> None:
    conn = pg_connect()
    cur = conn.cursor()

    # --- pg_stats の読み方（01） ---
    cur.execute("SELECT most_common_vals::text::text[], n_distinct FROM pg_stats "
                "WHERE tablename = 'orders' AND attname = 'status'")
    mcv, nd = cur.fetchone()
    check("E1 status の MCV は completed / pending / cancelled の 3 つで、先頭が completed",
          sorted(mcv) == ["cancelled", "completed", "pending"] and mcv[0] == "completed", str(mcv))
    check("E1 status の n_distinct は 3", nd == 3, str(nd))
    cur.execute("SELECT attname, correlation FROM pg_stats WHERE tablename = 'orders' "
                "AND attname IN ('id', 'ordered_at')")
    corr = dict(cur.fetchall())
    check("E1 orders.id の correlation は 1（物理順と完全に一致）", corr["id"] == 1, str(corr["id"]))
    check("E1 orders.ordered_at の correlation は 0 に近い", abs(corr["ordered_at"]) < 0.1, str(corr["ordered_at"]))
    cur.execute("SELECT most_common_vals IS NULL, array_length(histogram_bounds, 1) FROM pg_stats "
                "WHERE tablename = 'orders' AND attname = 'ordered_at'")
    no_mcv, nbounds = cur.fetchone()
    check("E1 ordered_at は MCV を持たず、ヒストグラムの境界値は 101 個", no_mcv and nbounds == 101, str(nbounds))
    cur.execute("SELECT n_distinct FROM pg_stats WHERE tablename = 'customers' AND attname = 'region'")
    check("E1 customers.region の n_distinct は 5", cur.fetchone()[0] == 5)

    # --- 等値条件の手計算（02） ---
    cur.execute("SELECT c.reltuples * s.most_common_freqs[array_position(s.most_common_vals::text::text[], 'pending')] "
                "FROM pg_stats s JOIN pg_class c ON c.relname = s.tablename "
                "WHERE s.tablename = 'orders' AND s.attname = 'status'")
    hand = cur.fetchone()[0]
    p = explain(cur, "SELECT * FROM orders WHERE status = 'pending'", analyze=False)
    check("E2 status = 'pending' の見積もりは reltuples × MCV の頻度", close(est(p), hand), f"{est(p)} / 手計算 {hand:.0f}")
    p = explain(cur, "SELECT * FROM orders WHERE status = 'refunded'", analyze=False)
    check("E2 MCV にない値（refunded）は 1 行と見積もられる", est(p) == 1, str(est(p)))
    cur.execute("SELECT c.reltuples / s.n_distinct FROM pg_stats s JOIN pg_class c ON c.relname = s.tablename "
                "WHERE s.tablename = 'orders' AND s.attname = 'customer_id'")
    hand = cur.fetchone()[0]
    p = explain(cur, "SELECT * FROM orders WHERE customer_id = 777", analyze=False)
    check("E2 customer_id = 777 の見積もりは reltuples / n_distinct", close(est(p), hand, 0.05),
          f"{est(p)} / 手計算 {hand:.1f}")
    p = explain(cur, "SELECT * FROM orders WHERE customer_id = 777")
    check("E2 customer_id = 777 の実際の行数は 20", round(actual_total_rows(find_nodes(p, "Seq Scan")[0])) == 20)

    # --- 範囲条件の手計算（03） ---
    cur.execute("""
        WITH h AS (
          SELECT histogram_bounds::text::timestamptz[] AS b
          FROM pg_stats WHERE tablename = 'orders' AND attname = 'ordered_at'
        ), pos AS (
          SELECT v.name,
                 (SELECT (i - 1 + extract(epoch FROM v.x - h.b[i]) / extract(epoch FROM h.b[i + 1] - h.b[i]))
                         / (array_length(h.b, 1) - 1)
                  FROM generate_series(1, array_length(h.b, 1) - 1) AS i
                  WHERE h.b[i] <= v.x AND v.x < h.b[i + 1]) AS position
          FROM h, (VALUES ('lo', timestamptz '2025-06-01'), ('hi', timestamptz '2025-06-08')) AS v(name, x)
        )
        SELECT (max(position) FILTER (WHERE name = 'hi') - max(position) FILTER (WHERE name = 'lo'))
               * (SELECT reltuples FROM pg_class WHERE relname = 'orders')
        FROM pos""")
    hand = float(cur.fetchone()[0])
    p = explain(cur, f"SELECT * FROM orders WHERE {WEEK}", analyze=False)
    check("E3 1 週間の見積もりはヒストグラムの按分で再現できる", close(est(p), hand), f"{est(p)} / 手計算 {hand:.0f}")
    cur.execute(f"SELECT count(*) FROM orders WHERE {WEEK}")
    check("E3 1 週間の実際の行数は 19,180", cur.fetchone()[0] == 19180)

    # --- 古い統計（04）と VACUUM では直らないこと（ex04） ---
    cur.execute("CREATE TABLE s06_orders WITH (autovacuum_enabled = false) AS SELECT * FROM orders")
    cur.execute("CREATE INDEX s06_orders_status_idx ON s06_orders (status)")
    cur.execute("ANALYZE s06_orders")
    cur.execute("INSERT INTO s06_orders (id, customer_id, ordered_at, status) "
                "SELECT id + 1000000, customer_id, ordered_at + interval '1 year', 'returned' "
                "FROM orders WHERE id % 4 = 0")
    p = explain(cur, STALE_JOIN)
    nl = find_nodes(p, "Nested Loop")
    check("E4 統計が古いと 'returned' を 1 行と見積もり Nested Loop を選ぶ", bool(nl) and est(p) == 1, str(node_types(p)))
    if nl:
        inner = nl[0]["Plans"][1]
        check("E4 実際は 25 万行で、内側の Index Scan が 25 万回ループする",
              round(actual_total_rows(nl[0])) == 250000 and inner["Actual Loops"] == 250000,
              f'loops={inner["Actual Loops"]}')
    cur.execute("VACUUM s06_orders")
    p = explain(cur, STALE_JOIN, analyze=False)
    check("E4 VACUUM しても列の統計は変わらず Nested Loop のまま", bool(find_nodes(p, "Nested Loop")) and est(p) == 1)
    cur.execute("ANALYZE s06_orders")
    cur.execute("SELECT most_common_vals::text::text[] FROM pg_stats WHERE tablename = 's06_orders' AND attname = 'status'")
    check("E4 ANALYZE で 'returned' が MCV に載る", "returned" in cur.fetchone()[0])
    p = explain(cur, STALE_JOIN)
    check("E4 ANALYZE 後は Hash Join に変わる", p["Plan"]["Node Type"] == "Hash Join", p["Plan"]["Node Type"])
    check("E4 ANALYZE 後の見積もりは実際（25 万行）と同じ桁", 100000 < est(p) < 500000, str(est(p)))

    # --- 自動 ANALYZE（05） ---
    cur.execute("CREATE TABLE s06_orders_auto WITH (autovacuum_enabled = false) AS SELECT * FROM orders")
    cur.execute("SELECT pg_stat_force_next_flush()")
    time.sleep(2)
    cur.execute("ANALYZE s06_orders_auto")
    cur.execute("ALTER TABLE s06_orders_auto SET (autovacuum_enabled = true)")
    cur.execute("INSERT INTO s06_orders_auto (id, customer_id, ordered_at, status) "
                "SELECT id + 1000000, customer_id, ordered_at + interval '1 year', 'returned' "
                "FROM orders WHERE id % 4 = 0")
    cur.execute("SELECT pg_stat_force_next_flush()")
    started = time.monotonic()
    ran = False
    while time.monotonic() - started < 90:
        time.sleep(2)
        cur.execute("SELECT pg_stat_clear_snapshot()")
        cur.execute("SELECT last_autoanalyze IS NOT NULL FROM pg_stat_user_tables WHERE relname = 's06_orders_auto'")
        if cur.fetchone()[0]:
            ran = True
            break
    check("E5 しきい値（50 + 0.1 × reltuples）を超える変更で自動 ANALYZE が走る", ran,
          f"{time.monotonic() - started:.0f} 秒後" if ran else "90 秒待っても走らなかった")

    # --- 列間の相関と拡張統計（06） ---
    cur.execute(f"SELECT count(*) FROM customers WHERE {TOKYO_DAY0}")
    actual = cur.fetchone()[0]
    check("E6 2024-01-01 生まれの東京の顧客は 71 人", actual == 71)
    cur.execute("SELECT count(*) FROM customers WHERE region = '大阪' AND created_at >= '2024-01-01' "
                "AND created_at < '2024-01-02'")
    check("E6 2024-01-01 生まれの大阪の顧客は 0 人", cur.fetchone()[0] == 0)
    p = explain(cur, f"SELECT * FROM customers WHERE {TOKYO_DAY0}", analyze=False)
    check("E6 拡張統計なし: 独立性の仮定で 71 人を大きく下回って見積もる", est(p) < 40, str(est(p)))
    p = explain(cur, "SELECT region, created_at, count(*) FROM customers GROUP BY region, created_at", analyze=False)
    check("E6 拡張統計なし: GROUP BY の組み合わせは 5 × 700 = 3,500 と見積もる", est(p) == 3500, str(est(p)))

    cur.execute("CREATE STATISTICS s06_cust_dep (dependencies) ON region, created_at FROM customers")
    cur.execute("ANALYZE customers")
    cur.execute("SELECT dependencies::text FROM pg_stats_ext WHERE statistics_name = 's06_cust_dep'")
    check("E6 dependencies は created_at → region の従属度 1.0 を記録する", '1.000000' in cur.fetchone()[0])
    p = explain(cur, f"SELECT * FROM customers WHERE {TOKYO_DAY0_EQ}", analyze=False)
    check("E6 dependencies: 等値条件なら 71 人前後に直る", 50 <= est(p) <= 100, str(est(p)))
    p = explain(cur, f"SELECT * FROM customers WHERE {TOKYO_DAY0}", analyze=False)
    check("E6 dependencies: 範囲条件には効かない", est(p) < 40, str(est(p)))
    cur.execute("DROP STATISTICS s06_cust_dep")

    cur.execute("CREATE STATISTICS s06_cust_mcv (mcv) ON region, created_at FROM customers")
    cur.execute("ANALYZE customers")
    cur.execute("SELECT array_length(most_common_vals, 1) FROM pg_stats_ext WHERE statistics_name = 's06_cust_mcv'")
    n_default = cur.fetchone()[0]
    check("E6 mcv: 既定の目標値では 700 通りのうち 100 個までしか持てない", n_default <= 100, str(n_default))
    cur.execute("ALTER STATISTICS s06_cust_mcv SET STATISTICS 1000")
    cur.execute("ANALYZE customers")
    cur.execute("SELECT array_length(most_common_vals, 1) FROM pg_stats_ext WHERE statistics_name = 's06_cust_mcv'")
    check("E6 mcv: 目標値 1000 で 700 通りすべてを持つ", cur.fetchone()[0] == 700)
    p = explain(cur, f"SELECT * FROM customers WHERE {TOKYO_DAY0}")
    check("E6 mcv（目標値 1000）: 範囲条件の見積もりが 71 人に直る", est(p) == 71 and actual_total_rows(p["Plan"]) == 71,
          str(est(p)))
    cur.execute("DROP STATISTICS s06_cust_mcv")

    cur.execute("CREATE STATISTICS s06_cust_nd (ndistinct) ON region, created_at FROM customers")
    cur.execute("ANALYZE customers")
    p = explain(cur, "SELECT region, created_at, count(*) FROM customers GROUP BY region, created_at")
    check("E6 ndistinct: GROUP BY の見積もりが 700 に直る", est(p) == 700 and actual_total_rows(p["Plan"]) == 700,
          str(est(p)))
    cur.execute("DROP STATISTICS s06_cust_nd")
    cur.execute("ANALYZE customers")

    # --- 統計の目標値（07） ---
    cur.execute("CREATE TABLE s06_hot WITH (autovacuum_enabled = false) AS "
                "SELECT i AS id, CASE WHEN i <= 200000 THEN 1 + (i % 200) "
                "ELSE 1 + ((i::bigint * 7919) % 50000)::int END AS customer_id "
                "FROM generate_series(1, 1000000) AS s(i)")
    cur.execute("ANALYZE s06_hot")
    mcv_sql = ("SELECT most_common_vals::text::int[] FROM pg_stats "
               "WHERE tablename = 's06_hot' AND attname = 'customer_id'")
    cur.execute(mcv_sql)
    mcv = cur.fetchone()[0]
    check("E7 既定の目標値（100）では MCV は 100 個", len(mcv) == 100, str(len(mcv)))
    hot_id = min(v for v in range(1, 201) if v not in mcv)
    p = explain(cur, f"SELECT * FROM s06_hot WHERE customer_id = {hot_id}")
    got = round(actual_total_rows(find_nodes(p, "Seq Scan")[0]))
    check("E7 MCV から漏れた常連客は実際の件数（1,016）より桁で小さく見積もられる",
          got == 1016 and est(p) * 10 < got, f"見積もり {est(p)} / 実際 {got}")
    cur.execute("ALTER TABLE s06_hot ALTER COLUMN customer_id SET STATISTICS 1000")
    cur.execute("ANALYZE s06_hot")
    cur.execute(mcv_sql)
    mcv = cur.fetchone()[0]
    check("E7 目標値 1000 では常連客 200 人全員が MCV に載る", all(v in mcv for v in range(1, 201)), str(len(mcv)))
    p = explain(cur, f"SELECT * FROM s06_hot WHERE customer_id = {hot_id}", analyze=False)
    check("E7 目標値 1000 では同じ客の見積もりが実際と同じ桁になる", 500 < est(p) < 2000, str(est(p)))

    # --- 統計が使えない書き方（08） ---
    cur.execute("SELECT reltuples FROM pg_class WHERE relname = 'orders'")
    reltuples = cur.fetchone()[0]
    p = explain(cur, "SELECT * FROM orders WHERE lower(status) = 'pending'", analyze=False)
    check("E8 lower(status) = ... は既定の選択率 0.5% で見積もられる", close(scan_rows_estimate(p), reltuples * 0.005),
          str(scan_rows_estimate(p)))
    p = explain(cur, "SELECT * FROM orders WHERE status = 'pending'", analyze=False)
    check("E8 status = 'pending' に書き換えると実際（136,646）と同じ桁", 100000 < scan_rows_estimate(p) < 200000,
          str(scan_rows_estimate(p)))
    cur.execute("CREATE STATISTICS s06_orders_lower_status ON (lower(status)) FROM orders")
    cur.execute("ANALYZE orders")
    p = explain(cur, "SELECT * FROM orders WHERE lower(status) = 'pending'", analyze=False)
    check("E8 式の拡張統計を作ると lower(status) でも実際と同じ桁", 100000 < scan_rows_estimate(p) < 200000,
          str(scan_rows_estimate(p)))
    cur.execute("DROP STATISTICS s06_orders_lower_status")
    cur.execute("ANALYZE orders")
    cur.execute("SELECT count(*) FROM orders WHERE lower(status) = 'pending'")
    check("E8 lower(status) = 'pending' の実際の行数は 136,646", cur.fetchone()[0] == 136646)
    conn.close()


def verify_mysql() -> None:
    conn = mysql_connect()
    try:
        with conn.cursor() as cur:
            def row(sql: str) -> dict:
                cur.execute("EXPLAIN FORMAT=TRADITIONAL " + sql)
                cols = [d[0] for d in cur.description]
                return dict(zip(cols, cur.fetchone()))

            cur.execute("ANALYZE TABLE orders DROP HISTOGRAM ON status")
            cur.fetchall()
            r = row("SELECT * FROM orders WHERE status = 'pending'")
            check("MySQL ヒストグラムなし: 等値条件の filtered は固定の 10%", float(r["filtered"]) == 10.0, str(r["filtered"]))
            cur.execute("ANALYZE TABLE orders UPDATE HISTOGRAM ON status WITH 8 BUCKETS")
            cur.fetchall()
            cur.execute("SELECT histogram->>'$.\"histogram-type\"' FROM information_schema.column_statistics "
                        "WHERE schema_name = DATABASE() AND table_name = 'orders' AND column_name = 'status'")
            check("MySQL 値の種類が少ない列のヒストグラムは singleton", cur.fetchone()[0] == "singleton")
            r = row("SELECT * FROM orders WHERE status = 'pending'")
            check("MySQL ヒストグラムあり: filtered が実際の割合（13.66%）に近づく", 13.0 < float(r["filtered"]) < 14.5,
                  str(r["filtered"]))
            cur.execute("ANALYZE TABLE orders DROP HISTOGRAM ON status")
            cur.fetchall()
    finally:
        conn.close()


if __name__ == "__main__":
    verify_pg()
    verify_mysql()
    finish("S06 統計情報とプランナ")

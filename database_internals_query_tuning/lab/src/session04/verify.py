"""セッション4（EXPLAIN (ANALYZE, BUFFERS) の読み方）の自己検証。

出発点（tools/reset.sh 直後）から単独で実行して成功すること。
ノードの種類・実測の行数・loops・触ったページの合計・クエリの結果で判定する。
（実行時間、見積もりの rows の正確な値、shared hit / read の内訳は判定に使わない）
"""

from __future__ import annotations

from labcheck import (actual_total_rows, check, explain, find_nodes, finish, mysql_connect,
                      node_types, pg_connect, walk)

DAY = "ordered_at >= '2025-06-01' AND ordered_at < '2025-06-02'"
HOUR = ("o.ordered_at >= '2025-06-01 10:00' AND o.ordered_at < '2025-06-01 11:00'")


def touched(node: dict) -> int:
    return node["Shared Hit Blocks"] + node["Shared Read Blocks"]


def verify_explain_vs_analyze(cur) -> None:
    plan = explain(cur, f"SELECT * FROM orders WHERE {DAY}", analyze=False)
    check("EXPLAIN だけでは実測（Actual Rows）が出ない",
          all("Actual Rows" not in n for n in walk(plan["Plan"])))
    cur.execute(f"EXPLAIN (ANALYZE, FORMAT JSON) SELECT * FROM orders WHERE {DAY}")
    plan = cur.fetchone()[0][0]
    check("EXPLAIN ANALYZE は実測を出す（1 日分 2740 行）",
          actual_total_rows(plan["Plan"]) == 2740)
    check("PostgreSQL 18 では ANALYZE だけで BUFFERS も出る", "Shared Hit Blocks" in plan["Plan"])

    cur.execute("DROP TABLE IF EXISTS s04_products")
    cur.execute("CREATE TABLE s04_products AS SELECT * FROM products")
    cur.execute("EXPLAIN DELETE FROM s04_products WHERE id <= 100")
    cur.fetchall()
    cur.execute("SELECT count(*) FROM s04_products")
    check("EXPLAIN DELETE は実行されない（5000 行のまま）", cur.fetchone()[0] == 5000)
    cur.execute("EXPLAIN ANALYZE DELETE FROM s04_products WHERE id <= 100")
    cur.fetchall()
    cur.execute("SELECT count(*) FROM s04_products")
    check("EXPLAIN ANALYZE DELETE は本当に削除する（4900 行）", cur.fetchone()[0] == 4900)


def verify_rollback_wrap() -> None:
    conn = pg_connect(autocommit=False)
    try:
        with conn.cursor() as cur:
            cur.execute("EXPLAIN ANALYZE UPDATE orders SET status = 'cancelled' WHERE id = 1")
            cur.fetchall()
            cur.execute("SELECT status FROM orders WHERE id = 1")
            inside = cur.fetchone()[0]
        conn.rollback()
        with conn.cursor() as cur:
            cur.execute("SELECT status FROM orders WHERE id = 1")
            after = cur.fetchone()[0]
        conn.rollback()
    finally:
        conn.close()
    check("BEGIN 内の EXPLAIN ANALYZE UPDATE は反映され、ROLLBACK で元に戻る",
          inside == "cancelled" and after == "completed", f"{inside} → {after}")


def verify_plan_tree(cur) -> None:
    sql = f"SELECT status, count(*) FROM orders WHERE {DAY} GROUP BY status ORDER BY status"
    plan = explain(cur, sql)
    types = node_types(plan)
    rows = [actual_total_rows(n) for n in walk(plan["Plan"])]
    check("計画木は Sort > Aggregate(Hashed) > Bitmap Heap Scan > Bitmap Index Scan",
          types == ["Sort", "Aggregate", "Bitmap Heap Scan", "Bitmap Index Scan"]
          and find_nodes(plan, "Aggregate")[0].get("Strategy") == "Hashed", " > ".join(types))
    check("内側から 2740 → 2740 → 3 → 3 行", rows == [3, 3, 2740, 2740], f"{rows}")
    cur.execute(sql)
    check("status 別件数は cancelled 119 / completed 2247 / pending 374",
          cur.fetchall() == [("cancelled", 119), ("completed", 2247), ("pending", 374)])


def verify_rows_mismatch(cur) -> None:
    plan = explain(cur, "SELECT * FROM customers WHERE region = '東京' AND created_at = '2024-03-01'")
    n = plan["Plan"]
    check("東京 × 2024-03-01: 実測 72 行に対し、見積もりは半分以下（大きくずれる）",
          actual_total_rows(n) == 72 and n["Plan Rows"] * 2 < 72,
          f"見積もり {n['Plan Rows']} / 実測 {actual_total_rows(n):.0f}")
    plan = explain(cur, "SELECT * FROM customers WHERE region = '大阪' AND created_at = '2024-03-01'")
    check("大阪 × 2024-03-01: 実測は 0 行", actual_total_rows(plan["Plan"]) == 0)
    cur.execute("SELECT count(DISTINCT region) FROM customers WHERE created_at = '2024-03-01'")
    check("2024-03-01 に登録した顧客は 1 地域だけ（条件どうしが独立でない）", cur.fetchone()[0] == 1)


def verify_buffers(cur) -> None:
    cur.execute("DROP TABLE IF EXISTS s04_orders")
    cur.execute("CREATE TABLE s04_orders AS SELECT * FROM orders")
    cur.execute("CREATE INDEX s04_orders_ordered_at_idx ON s04_orders (ordered_at)")
    cur.execute("VACUUM (ANALYZE) s04_orders")
    sql = f"SELECT * FROM s04_orders WHERE {DAY}"
    first = explain(cur, sql, buffers=True)["Plan"]
    second = explain(cur, sql, buffers=True)["Plan"]
    check("1 回目も 2 回目も触るページは 2750（ヒープ 2740 + インデックス 10）で同じ",
          touched(first) == touched(second) == 2750,
          f"1 回目 hit={first['Shared Hit Blocks']} read={first['Shared Read Blocks']} / "
          f"2 回目 hit={second['Shared Hit Blocks']} read={second['Shared Read Blocks']}")
    check("コストは 1 回目と 2 回目で同じ（キャッシュの状態を見ない）",
          first["Total Cost"] == second["Total Cost"])


def verify_loops(cur) -> None:
    plan = explain(cur, "SELECT o.id, c.name FROM orders o JOIN customers c ON c.id = o.customer_id "
                        f"WHERE {HOUR}", buffers=True)
    inner = [n for n in find_nodes(plan, "Index Scan") if n.get("Index Name") == "customers_pkey"]
    check("Nested Loop の内側（customers_pkey の Index Scan）が loops=116",
          plan["Plan"]["Node Type"] == "Nested Loop" and bool(inner)
          and inner[0]["Actual Loops"] == 116 and actual_total_rows(inner[0]) == 116)
    check("内側の Buffers は全ループの合計（116 回 × 3 ページ = 348）",
          bool(inner) and touched(inner[0]) == 348, f"{touched(inner[0]) if inner else None}")

    plan = explain(cur, "SELECT c.id, c.name, (SELECT count(*) FROM orders o WHERE o.customer_id = c.id) "
                        "FROM customers c WHERE c.id <= 5", buffers=True)
    agg = find_nodes(plan, "Aggregate")
    seq = find_nodes(plan, "Seq Scan")
    cur.execute("SELECT relpages FROM pg_class WHERE relname = 'orders'")
    pages = cur.fetchone()[0]
    check("相関サブクエリ（SubPlan）は loops=5", bool(agg) and agg[0]["Actual Loops"] == 5)
    check("SubPlan の Seq Scan の Buffers は orders 全ページ × 5 回",
          bool(seq) and touched(seq[0]) == pages * 5, f"{touched(seq[0]) if seq else None} / {pages * 5}")


def verify_three_queries(cur) -> None:
    q_in = f"SELECT * FROM customers WHERE id IN (SELECT customer_id FROM orders WHERE {DAY})"
    q_exists = ("SELECT * FROM customers c WHERE EXISTS (SELECT 1 FROM orders o WHERE o.customer_id = c.id "
                "AND o.ordered_at >= '2025-06-01' AND o.ordered_at < '2025-06-02')")
    q_distinct = ("SELECT DISTINCT c.* FROM customers c JOIN orders o ON o.customer_id = c.id "
                  "WHERE o.ordered_at >= '2025-06-01' AND o.ordered_at < '2025-06-02'")
    counts = []
    for q in (q_in, q_exists, q_distinct):
        cur.execute(f"SELECT count(*) FROM ({q}) t")
        counts.append(cur.fetchone()[0])
    cur.execute(f"SELECT count(*) FROM (({q_in}) EXCEPT ({q_distinct})) d")
    diff = cur.fetchone()[0]
    check("3 つの書き方の結果は同じ（2740 件・差集合 0 件）", counts == [2740] * 3 and diff == 0,
          f"{counts} / diff={diff}")
    p_in, p_ex, p_di = (explain(cur, q) for q in (q_in, q_exists, q_distinct))
    check("IN と EXISTS はプランナが同じ計画に書き換える", node_types(p_in) == node_types(p_ex),
          " > ".join(node_types(p_in)))
    check("JOIN + DISTINCT は結合してから全列で重複を除く（最上位が Aggregate / Unique）",
          p_di["Plan"]["Node Type"] in ("Aggregate", "Unique")
          and node_types(p_di) != node_types(p_in), " > ".join(node_types(p_di)))


def verify_cast_vs_range(cur) -> None:
    cast = explain(cur, "SELECT * FROM orders WHERE ordered_at::date = '2025-06-01'")
    rng = explain(cur, f"SELECT * FROM orders WHERE {DAY}")
    idx_nodes = {"Index Scan", "Bitmap Index Scan", "Index Only Scan"}
    check("ordered_at::date = 日付 はインデックスを使えない（全表走査）",
          not idx_nodes & set(node_types(cast)) and actual_total_rows(cast["Plan"]) == 2740,
          " > ".join(node_types(cast)))
    check("範囲条件なら Bitmap Heap Scan（結果は同じ 2740 行）",
          rng["Plan"]["Node Type"] == "Bitmap Heap Scan" and actual_total_rows(rng["Plan"]) == 2740)


def verify_cost(cur) -> None:
    cur.execute("SELECT relpages, reltuples FROM pg_class WHERE relname = 'orders'")
    relpages, reltuples = cur.fetchone()
    cur.execute("SET max_parallel_workers_per_gather = 0")
    for ops, where in ((0, ""), (1, " WHERE status = 'pending'"),
                       (2, " WHERE status = 'pending' AND customer_id = 1")):
        plan = explain(cur, f"SELECT * FROM orders{where}", analyze=False)
        want = relpages * 1.0 + reltuples * 0.01 + reltuples * 0.0025 * ops
        got = plan["Plan"]["Total Cost"]
        check(f"Seq Scan のコスト = ページ数 × 1.0 + 行数 × (0.01 + 0.0025 × {ops})",
              abs(got - want) < 0.01, f"EXPLAIN {got} / 計算 {want:.2f}")
    cur.execute("RESET max_parallel_workers_per_gather")


def verify_mysql() -> None:
    conn = mysql_connect()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM information_schema.statistics WHERE table_schema = DATABASE() "
                        "AND table_name = 'orders' AND index_name = 'idx_orders_ordered_at'")
            if cur.fetchone()[0] == 0:
                cur.execute("CREATE INDEX idx_orders_ordered_at ON orders (ordered_at)")
            cur.execute("EXPLAIN ANALYZE SELECT o.id, c.name FROM orders o JOIN customers c "
                        "ON c.id = o.customer_id WHERE " + HOUR)
            tree = cur.fetchone()[0]
            inner = [line for line in tree.splitlines() if "customers" in line or "on c using PRIMARY" in line]
            check("MySQL: EXPLAIN ANALYZE でも内側の主キー参照が loops=116",
                  any("loops=116" in line for line in inner), inner[0].strip() if inner else tree)
            cur.execute("DROP TABLE IF EXISTS s04_products")
            cur.execute("CREATE TABLE s04_products AS SELECT * FROM products")
            cur.execute("EXPLAIN ANALYZE DELETE FROM s04_products WHERE id <= 100")
            out = cur.fetchone()[0]
            cur.execute("SELECT count(*) FROM s04_products")
            n = cur.fetchone()[0]
            check("MySQL: 1 テーブルの DELETE は EXPLAIN ANALYZE の対象外で、行は消えない",
                  "not executable" in out and n == 5000, f"{out.strip()} / {n} 行")
            cur.execute("DROP TABLE s04_products")
    finally:
        conn.close()


def main() -> None:
    with pg_connect() as conn, conn.cursor() as cur:
        cur.execute("CREATE INDEX IF NOT EXISTS orders_ordered_at_idx ON orders (ordered_at)")
        verify_explain_vs_analyze(cur)
        verify_plan_tree(cur)
        verify_rows_mismatch(cur)
        verify_buffers(cur)
        verify_loops(cur)
        verify_three_queries(cur)
        verify_cast_vs_range(cur)
        verify_cost(cur)
    verify_rollback_wrap()
    verify_mysql()
    finish("セッション4")


if __name__ == "__main__":
    main()

"""Review02 横断復習②（S06〜S08）— 自己検証。

出発点（tools/reset.sh 直後）から単独で実行する。遅いクエリ A（統計）・B（設計）・C（プランナの前提）と
練習問題の素材（スキャン方式・拡張統計・LEFT JOIN）を、章の SQL と同じ手順で作って確かめる。
"""

from __future__ import annotations

import statistics

from labcheck import (actual_total_rows, check, explain, find_nodes, finish,
                      node_types, pg_connect)

QUERY_A = """
SELECT c.region, o.customer_id, sum(i.quantity * i.unit_price) AS sales
FROM r02_daily_orders o
JOIN r02_daily_items i ON i.order_id = o.order_id
JOIN customers c ON c.id = o.customer_id
WHERE o.batch_date = '2025-12-01' AND i.batch_date = '2025-12-01'
  AND o.status <> 'cancelled'
GROUP BY c.region, o.customer_id
ORDER BY sales DESC, o.customer_id
LIMIT 10
"""
QUERY_B = """
SELECT o.id, o.ordered_at, sum(oi.quantity * oi.unit_price) AS amount
FROM orders o
JOIN order_items oi ON oi.order_id = o.id
WHERE o.customer_id = 777 AND o.status <> 'cancelled'
GROUP BY o.id, o.ordered_at
ORDER BY o.ordered_at DESC
LIMIT 5
"""
QUERY_C = """
SELECT sum(oi.quantity * oi.unit_price) AS sales, count(*) AS lines
FROM orders o
JOIN order_items oi ON oi.order_id = o.id
JOIN products p ON p.id = oi.product_id
WHERE o.ordered_at >= '2025-03-01' AND o.ordered_at < '2025-03-08'
  AND o.status <> 'cancelled'
  AND p.category = '文具'
"""
CORRELATED = """
SELECT count(*) FROM customers c JOIN orders o ON o.customer_id = c.id
WHERE c.region = '大阪' AND c.created_at = '2024-01-02'
"""
SALES_ALL = """
SELECT count(*), sum(sales) FROM (
  SELECT c.id, coalesce(sum(oi.quantity * oi.unit_price), 0) AS sales
  FROM customers c
  LEFT JOIN orders o ON o.customer_id = c.id
   AND o.ordered_at >= '2025-03-01' AND o.ordered_at < '2025-03-02' {on_extra}
  LEFT JOIN order_items oi ON oi.order_id = o.id
  {where}
  GROUP BY c.id
) AS s
"""


def settings(cur, *stmts: str) -> None:
    cur.execute("RESET ALL")
    for s in stmts:
        cur.execute(s)


def joins(plan: dict) -> list[str]:
    return [t for t in node_types(plan) if t in ("Hash Join", "Merge Join", "Nested Loop")]


def median_time(cur, sql: str, rounds: int = 5) -> float:
    return statistics.median(explain(cur, sql)["Execution Time"] for _ in range(rounds))


def main() -> None:
    conn = pg_connect()
    cur = conn.cursor()

    # --- 遅いクエリ A：統計が前日のままの作業用テーブル ---
    cur.execute("DROP TABLE IF EXISTS r02_daily_items, r02_daily_orders")
    cur.execute("""CREATE TABLE r02_daily_orders (batch_date date NOT NULL, order_id bigint NOT NULL,
                   customer_id integer NOT NULL, status text NOT NULL) WITH (autovacuum_enabled = false)""")
    cur.execute("""CREATE TABLE r02_daily_items (batch_date date NOT NULL, order_id bigint NOT NULL,
                   product_id integer NOT NULL, quantity integer NOT NULL, unit_price integer NOT NULL)
                   WITH (autovacuum_enabled = false)""")
    for frm, to in (("2025-11-30", "2025-12-01"), ("2025-12-01", "2025-12-02")):
        cur.execute("INSERT INTO r02_daily_orders SELECT ordered_at::date, id, customer_id, status FROM orders "
                    f"WHERE ordered_at >= '{frm}' AND ordered_at < '{to}'")
        cur.execute("INSERT INTO r02_daily_items SELECT o.ordered_at::date, oi.order_id, oi.product_id, "
                    "oi.quantity, oi.unit_price FROM order_items oi JOIN orders o ON o.id = oi.order_id "
                    f"WHERE o.ordered_at >= '{frm}' AND o.ordered_at < '{to}'")
        if frm == "2025-11-30":
            cur.execute("ANALYZE r02_daily_orders, r02_daily_items")

    settings(cur)
    plan = explain(cur, QUERY_A)
    inner = [n for n in find_nodes(plan, "Seq Scan") if n.get("Relation Name") == "r02_daily_items"]
    check("A: 作業用テーブル同士が Nested Loop で結合される", "Nested Loop" in joins(plan) and "Hash Join" not in joins(plan),
          str(joins(plan)))
    check("A: 内側の r02_daily_items を 2,620 回読み直す", bool(inner) and inner[0]["Actual Loops"] == 2620)
    sorts = [n.get("Sort Method") for n in find_nodes(plan, "Sort")]
    check("A: ソートはすべてメモリ内（外部ソートではない）", sorts and "external merge" not in sorts, str(sorts))
    cur.execute(QUERY_A)
    before = cur.fetchall()
    slow = median_time(cur, QUERY_A)

    settings(cur, "SET work_mem = '64MB'")
    plan = explain(cur, QUERY_A)
    check("A: work_mem を 64MB にしても Nested Loop のまま", "Hash Join" not in joins(plan), str(joins(plan)))
    settings(cur)

    cur.execute("SELECT most_common_vals::text FROM pg_stats "
                "WHERE tablename = 'r02_daily_orders' AND attname = 'batch_date'")
    check("A: 統計が知っている batch_date は前日だけ", cur.fetchone()[0] == "{2025-11-30}")

    cur.execute("ANALYZE r02_daily_orders, r02_daily_items")
    plan = explain(cur, QUERY_A)
    check("A: ANALYZE 後は Hash Join", "Nested Loop" not in joins(plan) and "Hash Join" in joins(plan), str(joins(plan)))
    fast = median_time(cur, QUERY_A)
    check("A: ANALYZE で 10 倍以上速くなる", slow > 10 * fast, f"{slow:.1f} ms → {fast:.1f} ms")
    cur.execute(QUERY_A)
    after = cur.fetchall()
    check("A: 結果は ANALYZE の前後で同じ（トップは顧客 17・5,909 円）",
          before == after and after[0][1:] == (17, 5909), str(after[0]))

    # --- 遅いクエリ B：インデックスが足りない（設計） ---
    plan = explain(cur, QUERY_B)
    seqs = sorted({n.get("Relation Name") for n in find_nodes(plan, "Seq Scan")}
                  | {n.get("Relation Name") for n in find_nodes(plan, "Parallel Seq Scan")})
    parallel = [n for n in node_types(plan) if n.startswith("Parallel Seq Scan")]
    check("B: 出発点では orders と order_items を全件読む", bool(parallel) or seqs == ["order_items", "orders"],
          str(node_types(plan)))
    cur.execute("CREATE INDEX orders_customer_id_ordered_at_idx ON orders (customer_id, ordered_at)")
    cur.execute("CREATE INDEX order_items_order_id_idx ON order_items (order_id)")
    plan = explain(cur, QUERY_B)
    idx = {n.get("Index Name") for n in find_nodes(plan, "Index Scan")}
    check("B: 2 つのインデックスで Nested Loop になる",
          {"orders_customer_id_ordered_at_idx", "order_items_order_id_idx"} <= idx and "Nested Loop" in joins(plan),
          str(idx))
    cur.execute(QUERY_B)
    rows = cur.fetchall()
    check("B: 顧客 777 の直近 5 件（先頭は注文 18904・1,123 円）", len(rows) == 5 and rows[0][0] == 18904
          and rows[0][2] == 1123, str(rows[0]))

    # --- 遅いクエリ C：統計も設計も正しいが、コスト定数の前提が環境と合わない ---
    cur.execute("DROP INDEX orders_customer_id_ordered_at_idx")
    settings(cur, "SET max_parallel_workers_per_gather = 0")
    plan = explain(cur, QUERY_C)
    check("C: 既定では Hash Join 2 段", joins(plan) == ["Hash Join", "Hash Join"], str(joins(plan)))
    settings(cur, "SET max_parallel_workers_per_gather = 0", "SET random_page_cost = 1.1")
    plan = explain(cur, QUERY_C)
    idx = [n for n in find_nodes(plan, "Index Scan") if n.get("Index Name") == "order_items_order_id_idx"]
    check("C: random_page_cost = 1.1 ではプランナが自分で Nested Loop（インデックス）を選ぶ",
          "Nested Loop" in joins(plan) and bool(idx), str(joins(plan)))
    settings(cur)
    cur.execute(QUERY_C)
    check("C: 売上と明細行数", cur.fetchone() == (10055263, 9174))

    # --- 練習：スキャン方式（S05） ---
    cur.execute("CREATE INDEX orders_ordered_at_idx ON orders (ordered_at)")
    plan = explain(cur, "SELECT * FROM orders WHERE ordered_at >= '2025-03-01' AND ordered_at < '2025-03-02'",
                   analyze=False)
    check("練習: 1 日分の SELECT * は Bitmap Heap Scan", node_types(plan)[0] == "Bitmap Heap Scan", str(node_types(plan)))
    plan = explain(cur, "SELECT * FROM orders WHERE ordered_at >= '2025-01-01' AND ordered_at < '2025-07-01'",
                   analyze=False)
    check("練習: 6 か月分の SELECT * は Seq Scan", node_types(plan) == ["Seq Scan"], str(node_types(plan)))
    plan = explain(cur, "SELECT count(*) FROM orders WHERE ordered_at >= '2025-01-01' AND ordered_at < '2025-07-01'",
                   analyze=False)
    check("練習: 6 か月分でも count(*) は Index Only Scan",
          any(t.endswith("Index Only Scan") for t in node_types(plan)), str(node_types(plan)))

    # --- 練習：相関のある 2 条件と拡張統計（S06） ---
    cur.execute("CREATE INDEX orders_customer_id_ordered_at_idx ON orders (customer_id, ordered_at)")
    plan = explain(cur, CORRELATED)
    shape_before = node_types(plan)
    check("練習: 2024-01-02 登録の大阪の顧客の注文は 1,440 件", actual_total_rows(find_nodes(plan, "Nested Loop")[0]) == 1440)
    cur.execute("CREATE STATISTICS customers_region_created_at_dep (dependencies) ON region, created_at FROM customers")
    cur.execute("ANALYZE customers")
    cur.execute("SELECT dependencies::text FROM pg_stats_ext WHERE statistics_name = 'customers_region_created_at_dep'")
    deps = cur.fetchone()[0]
    check("練習: created_at → region の関数従属度は 1.0", '"5 => 4": 1.000000' in deps, deps)
    plan = explain(cur, CORRELATED)
    check("練習: 拡張統計を作っても計画の形は変わらない", node_types(plan) == shape_before, str(node_types(plan)))

    # --- 練習：LEFT JOIN と WHERE（S07） ---
    cur.execute(SALES_ALL.format(on_extra="", where="WHERE o.status <> 'cancelled'"))
    wrong = cur.fetchone()
    cur.execute(SALES_ALL.format(on_extra="AND o.status <> 'cancelled'", where=""))
    right = cur.fetchone()
    check("練習: キャンセル除外を WHERE に書くと顧客が 2,621 人に減る", wrong == (2621, 5747385), str(wrong))
    check("練習: ON に書けば 50,000 人全員が残り、売上合計は同じ", right == (50000, 5747385), str(right))
    conn.close()

    finish("Review02 横断復習②")


if __name__ == "__main__":
    main()

"""S07 結合アルゴリズム — 自己検証。

出発点（tools/reset.sh 直後）から単独で実行する。章の SQL と同じインデックス・作業用テーブルを自分で作る。
判定に使うのはノードの種類・実測の行数・クエリの結果・計画メモリ（決定的）と、10 倍以上の差がある時間の大小だけ。
"""

from __future__ import annotations

import statistics

from labcheck import (actual_total_rows, check, explain, find_nodes, finish,
                      mysql_connect, node_types, pg_connect, walk)

THREE_TABLES = """
SELECT sum(oi.quantity * oi.unit_price) AS sales, count(*) AS lines
FROM orders o
JOIN order_items oi ON oi.order_id = o.id
JOIN products p ON p.id = oi.product_id
WHERE o.ordered_at >= '2025-03-01' AND o.ordered_at < '{to}'
  AND o.status <> 'cancelled'
  AND p.category = '文具'
"""
WEEK = THREE_TABLES.format(to="2025-03-08")
DAY = THREE_TABLES.format(to="2025-03-02")

BAD_ORDER = """
SELECT sum(oi.quantity * oi.unit_price) AS sales, count(*) AS lines
FROM order_items oi
JOIN products p ON p.id = oi.product_id
JOIN orders o ON o.id = oi.order_id
WHERE o.ordered_at >= '2025-03-01' AND o.ordered_at < '2025-03-02'
  AND o.status <> 'cancelled'
  AND p.category = '文具'
"""

ORDER_DETAIL = """
SELECT o.id, o.ordered_at, p.name, oi.quantity, oi.unit_price
FROM orders o
JOIN order_items oi ON oi.order_id = o.id
JOIN products p ON p.id = oi.product_id
WHERE o.id = 500000
"""

STAGE_QUERY = """
SELECT sum(i.quantity * i.unit_price) AS sales, count(*) AS lines
FROM s07_stage_orders o
JOIN s07_stage_items i ON i.order_id = o.order_id
WHERE o.batch_date = '2025-12-31' AND i.batch_date = '2025-12-31'
  AND o.status <> 'cancelled'
"""

LEFT_ON = """
SELECT count(*), count(o.id) FROM customers c
LEFT JOIN orders o ON o.customer_id = c.id
 AND o.ordered_at >= '2025-03-01' AND o.ordered_at < '2025-03-06'
"""
LEFT_WHERE = """
SELECT count(*), count(o.id) FROM customers c
LEFT JOIN orders o ON o.customer_id = c.id
WHERE o.ordered_at >= '2025-03-01' AND o.ordered_at < '2025-03-06'
"""
LEFT_ON_REGION = """
SELECT count(*), count(o.id) FROM customers c
LEFT JOIN orders o ON o.customer_id = c.id
 AND o.ordered_at >= '2025-03-01' AND o.ordered_at < '2025-03-06'
 AND c.region = '東京'
"""


def joins(plan: dict) -> list[str]:
    return [t for t in node_types(plan) if t in ("Hash Join", "Merge Join", "Nested Loop")]


def settings(cur, *stmts: str) -> None:
    cur.execute("RESET ALL")
    for s in stmts:
        cur.execute(s)


def median_times(cur, variants, rounds: int = 5) -> dict[str, float]:
    """variants: (名前, [SET 文], SQL)。交互に rounds 回ずつ EXPLAIN ANALYZE の Execution Time を取り、中央値を返す"""
    times: dict[str, list[float]] = {name: [] for name, _, _ in variants}
    for _ in range(rounds):
        for name, stmts, sql in variants:
            settings(cur, *stmts)
            times[name].append(explain(cur, sql)["Execution Time"])
    cur.execute("RESET ALL")
    return {name: statistics.median(ts) for name, ts in times.items()}


def create_stage_tables(cur) -> None:
    cur.execute("DROP TABLE IF EXISTS s07_stage_items, s07_stage_orders")
    cur.execute("""CREATE TABLE s07_stage_orders (batch_date date NOT NULL, order_id bigint NOT NULL,
                   customer_id integer NOT NULL, status text NOT NULL) WITH (autovacuum_enabled = false)""")
    cur.execute("""CREATE TABLE s07_stage_items (batch_date date NOT NULL, order_id bigint NOT NULL,
                   product_id integer NOT NULL, quantity integer NOT NULL, unit_price integer NOT NULL)
                   WITH (autovacuum_enabled = false)""")
    for frm, to in (("2025-12-30", "2025-12-31"), ("2025-12-31", "2026-01-01")):
        cur.execute("INSERT INTO s07_stage_orders SELECT ordered_at::date, id, customer_id, status FROM orders "
                    "WHERE ordered_at >= %s AND ordered_at < %s", (frm, to))
        cur.execute("INSERT INTO s07_stage_items SELECT o.ordered_at::date, oi.order_id, oi.product_id, "
                    "oi.quantity, oi.unit_price FROM order_items oi JOIN orders o ON o.id = oi.order_id "
                    "WHERE o.ordered_at >= %s AND o.ordered_at < %s", (frm, to))
        if frm == "2025-12-30":
            cur.execute("ANALYZE s07_stage_orders, s07_stage_items")


def planner_memory_kb(cur, n: int) -> int:
    q = ("SELECT count(*) FROM " + ", ".join(f"s07_t{i}" for i in range(1, n + 1)) + " WHERE "
         + " AND ".join(f"s07_t{i}.id = s07_t{i + 1}.id" for i in range(1, n)))
    cur.execute("EXPLAIN (FORMAT JSON, SUMMARY, MEMORY, COSTS OFF) " + q)
    return int(cur.fetchone()[0][0]["Planning"]["Memory Used"])


def main() -> None:
    conn = pg_connect()
    cur = conn.cursor()

    # --- E1/E2: 出発点（インデックスは主キーだけ）での 3 方式 ---
    settings(cur, "SET max_parallel_workers_per_gather = 0")
    cur.execute(WEEK)
    expected = cur.fetchone()
    check("1週間・文具の売上と明細行数", expected == (10055263, 9174), str(expected))

    plan = explain(cur, WEEK)
    check("出発点の既定プランは Hash Join 2 段", joins(plan) == ["Hash Join", "Hash Join"], str(joins(plan)))

    settings(cur, "SET max_parallel_workers_per_gather = 0", "SET enable_hashjoin = off", "SET enable_mergejoin = off")
    plan = explain(cur, WEEK)
    orders_pk = [n for n in find_nodes(plan, "Index Scan") if n.get("Index Name") == "orders_pkey"]
    check("Nested Loop だけ：Nested Loop 2 段", joins(plan) == ["Nested Loop", "Nested Loop"], str(joins(plan)))
    check("Nested Loop だけ：orders_pkey を 50万回引く（order_items 側が外側になる）",
          bool(orders_pk) and orders_pk[0]["Actual Loops"] == 500000,
          str([n["Actual Loops"] for n in orders_pk]))

    settings(cur, "SET max_parallel_workers_per_gather = 0", "SET enable_hashjoin = off", "SET enable_nestloop = off")
    plan = explain(cur, WEEK)
    ext = [n for n in find_nodes(plan, "Sort") if n.get("Sort Method") == "external merge"]
    check("Merge Join だけ：Merge Join 2 段で order_items を外部ソートする",
          joins(plan) == ["Merge Join", "Merge Join"] and len(ext) == 1, str(joins(plan)))
    cur.execute(WEEK)
    check("Merge Join でも結果は同じ", cur.fetchone() == expected)

    # --- E3: order_items(order_id) のインデックス ---
    cur.execute("CREATE INDEX order_items_order_id_idx ON order_items (order_id)")
    settings(cur, "SET max_parallel_workers_per_gather = 0")
    plan = explain(cur, WEEK)
    check("インデックスがあっても 1 週間は Hash Join のまま", joins(plan) == ["Hash Join", "Hash Join"], str(joins(plan)))
    plan = explain(cur, DAY)
    idx = [n for n in find_nodes(plan, "Index Scan") if n.get("Index Name") == "order_items_order_id_idx"]
    check("1 日分なら Nested Loop ＋ order_items_order_id_idx", "Nested Loop" in joins(plan) and bool(idx),
          str(joins(plan)))

    # --- E4: 注文 1 件の明細 ---
    settings(cur)
    plan = explain(cur, ORDER_DETAIL)
    check("注文 1 件の明細は Nested Loop 2 段", joins(plan) == ["Nested Loop", "Nested Loop"], str(joins(plan)))
    check("注文 500000 の明細は 3 行", actual_total_rows(plan["Plan"]) == 3)

    # --- E5: 結合順序 ---
    cur.execute("CREATE INDEX orders_ordered_at_idx ON orders (ordered_at)")
    settings(cur, "SET max_parallel_workers_per_gather = 0")
    plan = explain(cur, BAD_ORDER)
    seq_items = [n for n in find_nodes(plan, "Seq Scan") if n.get("Relation Name") == "order_items"]
    check("既定ではプランナが並べ替え、order_items を全件読まない", not seq_items)
    settings(cur, "SET max_parallel_workers_per_gather = 0", "SET join_collapse_limit = 1")
    plan = explain(cur, BAD_ORDER)
    big = [n for n in find_nodes(plan, "Hash Join") if actual_total_rows(n) == 500000]
    check("join_collapse_limit = 1 では order_items × products の 50万行が先にできる", bool(big))
    t = median_times(cur, [
        ("default", ["SET max_parallel_workers_per_gather = 0"], BAD_ORDER),
        ("written", ["SET max_parallel_workers_per_gather = 0", "SET join_collapse_limit = 1"], BAD_ORDER),
    ])
    check("書いた順の結合は既定より 10 倍以上遅い", t["written"] > 10 * t["default"],
          f"{t['written']:.1f} ms / {t['default']:.1f} ms")

    # --- E6: 統計が前日のままの作業用テーブル ---
    create_stage_tables(cur)
    settings(cur)
    plan = explain(cur, STAGE_QUERY)
    inner = [n for n in find_nodes(plan, "Seq Scan") if n.get("Relation Name") == "s07_stage_items"]
    check("統計が古いと Nested Loop が選ばれる", joins(plan) == ["Nested Loop"], str(joins(plan)))
    check("内側の s07_stage_items を 2,620 回読み直す", bool(inner) and inner[0]["Actual Loops"] == 2620,
          str([n["Actual Loops"] for n in inner]))
    t = median_times(cur, [
        ("stale", [], STAGE_QUERY),
        ("no_nestloop", ["SET enable_nestloop = off"], STAGE_QUERY),
    ])
    check("Nested Loop は Hash Join より 10 倍以上遅い", t["stale"] > 10 * t["no_nestloop"],
          f"{t['stale']:.1f} ms / {t['no_nestloop']:.1f} ms")
    cur.execute("ANALYZE s07_stage_orders, s07_stage_items")
    plan = explain(cur, STAGE_QUERY)
    check("ANALYZE 後はプランナが自分で Hash Join を選ぶ", joins(plan) == ["Hash Join"], str(joins(plan)))
    cur.execute(STAGE_QUERY)
    check("作業用テーブルの当日売上", cur.fetchone() == (5750971, 5240))

    # --- E7: 結合するテーブル数と計画メモリ（geqo = off の全探索は 10 個まで） ---
    for i in range(1, 13):
        cur.execute(f"DROP TABLE IF EXISTS s07_t{i}")
        cur.execute(f"CREATE TABLE s07_t{i} AS SELECT g AS id FROM generate_series(1, 100) AS g")
        cur.execute(f"ANALYZE s07_t{i}")
    settings(cur)
    m8, m10, m12 = planner_memory_kb(cur, 8), planner_memory_kb(cur, 10), planner_memory_kb(cur, 12)
    check("8 → 10 テーブルで計画メモリが 5 倍以上に増える", m10 > 5 * m8, f"{m8} kB → {m10} kB")
    check("12 テーブルでは GEQO に切り替わり計画メモリが激減する", m12 * 10 < m10, f"{m12} kB")

    # --- E8: LEFT JOIN の条件の位置 ---
    cur.execute(LEFT_ON)
    check("ON に書くと全顧客 50,000 行が残る", cur.fetchone() == (50000, 13700))
    cur.execute(LEFT_WHERE)
    check("WHERE に書くと 13,700 行に減る", cur.fetchone() == (13700, 13700))
    cur.execute(LEFT_ON_REGION)
    check("左側の条件を ON に書いても左側の行は減らない", cur.fetchone() == (50000, 2740))
    plan = explain(cur, LEFT_WHERE)
    types = [n.get("Join Type") for n in walk(plan["Plan"]) if "Join Type" in n]
    check("WHERE 版は内部結合に書き換えられる（Join Type が Inner）", types == ["Inner"], str(types))
    plan = explain(cur, LEFT_ON)
    types = [n.get("Join Type") for n in walk(plan["Plan"]) if "Join Type" in n]
    check("ON 版は外部結合のまま（Right か Left）", len(types) == 1 and types[0] in ("Right", "Left"), str(types))
    conn.close()

    # --- MySQL: インデックスの無い等値結合は Hash Join ---
    my = mysql_connect()
    with my.cursor() as mc:
        mc.execute("DROP TABLE IF EXISTS s07_my_a, s07_my_b")
        mc.execute("CREATE TABLE s07_my_a (order_id BIGINT NOT NULL)")
        mc.execute("CREATE TABLE s07_my_b (order_id BIGINT NOT NULL, amount INT NOT NULL)")
        mc.execute("INSERT INTO s07_my_a SELECT id FROM orders WHERE id <= 1000")
        mc.execute("INSERT INTO s07_my_b SELECT order_id, quantity * unit_price FROM order_items WHERE order_id <= 1000")
        mc.execute("EXPLAIN FORMAT=TREE SELECT SUM(b.amount) FROM s07_my_a a JOIN s07_my_b b ON b.order_id = a.order_id")
        tree = mc.fetchone()[0]
        check("MySQL: インデックスの無い等値結合は hash join", "hash join" in tree.lower(), tree.splitlines()[1].strip())
        mc.execute("DROP TABLE s07_my_a, s07_my_b")
    my.close()

    finish("S07 結合アルゴリズム")


if __name__ == "__main__":
    main()

"""Mid01 中間プロジェクト（遅いクエリを速くする）— 自己検証。

出発点（tools/reset.sh 直後）から単独で実行する。章の SQL と同じインデックス・作業用テーブルを自分で作る。
判定に使うのはノードの種類・実測の行数・クエリの結果と、10 倍以上の差がある時間の大小だけ。
"""

from __future__ import annotations

import statistics

import psycopg

from labcheck import (actual_total_rows, check, explain, find_nodes, finish,
                      mysql_connect, node_types, walk)

A_BEFORE = """
SELECT o.id, o.ordered_at, o.status
FROM customers c JOIN orders o ON o.customer_id = c.id
WHERE lower(c.email) = lower('User12345@Example.com')
ORDER BY o.ordered_at DESC
"""
A_AFTER = """
SELECT o.id, o.ordered_at, o.status
FROM customers c JOIN orders o ON o.customer_id = c.id
WHERE c.email = lower('User12345@Example.com')
ORDER BY o.ordered_at DESC
"""
B_QUERY = """
SELECT count(*) AS dup_lines
FROM mid01_import a
JOIN mid01_import b
  ON b.order_id = a.order_id AND b.product_id = a.product_id AND b.line_no > a.line_no
WHERE a.batch_date = DATE '2025-12-31' AND b.batch_date = DATE '2025-12-31'
"""
C_BEFORE = """
SELECT id, customer_id, ordered_at
FROM (SELECT id, customer_id, ordered_at, row_number() OVER (ORDER BY ordered_at DESC) AS rn
      FROM orders WHERE status = 'pending') t
WHERE rn <= 20
ORDER BY rn
"""
C_AFTER = """
SELECT id, customer_id, ordered_at
FROM orders WHERE status = 'pending'
ORDER BY ordered_at DESC
LIMIT 20
"""

LOAD_DAY = """
INSERT INTO mid01_import
SELECT o.ordered_at::date, oi.order_id,
       row_number() OVER (PARTITION BY oi.order_id ORDER BY oi.id),
       oi.product_id, oi.quantity, oi.unit_price
FROM order_items oi JOIN orders o ON o.id = oi.order_id
WHERE o.ordered_at >= %s AND o.ordered_at < %s
"""
ADD_DUPLICATES = """
INSERT INTO mid01_import
SELECT batch_date, order_id, line_no + 10, product_id, quantity, unit_price
FROM mid01_import
WHERE line_no = 1
  AND order_id IN (SELECT DISTINCT order_id FROM mid01_import ORDER BY order_id LIMIT 3)
"""


def stale_import(cur) -> None:
    """05 と同じ手順：昨夜分で ANALYZE → TRUNCATE → 今夜分（＋重複 3 行）。統計は昨夜のまま"""
    cur.execute("TRUNCATE mid01_import")
    cur.execute(LOAD_DAY, ("2025-12-30", "2025-12-31"))
    cur.execute("ANALYZE mid01_import")
    cur.execute("TRUNCATE mid01_import")
    cur.execute(LOAD_DAY, ("2025-12-31", "2026-01-01"))
    cur.execute(ADD_DUPLICATES)


def exec_ms(cur, sql: str) -> float:
    cur.execute("EXPLAIN (ANALYZE, TIMING OFF, FORMAT JSON) " + sql)
    return cur.fetchone()[0][0]["Execution Time"]


def joins(plan: dict) -> list[str]:
    return [t for t in node_types(plan) if t in ("Hash Join", "Merge Join", "Nested Loop")]


def scans_on(plan: dict, relation: str) -> list[dict]:
    return [n for n in walk(plan["Plan"]) if n.get("Relation Name") == relation]


def main() -> None:
    # 同じ SQL を何度も実行するので、自動プリペアを止める（止めないと SET や統計の変化が計画に効かなくなる）
    conn = psycopg.connect(autocommit=True, prepare_threshold=None)
    cur = conn.cursor()

    # --- 01: 題材のシステムにもともとあるインデックス ---
    cur.execute("CREATE INDEX customers_email_idx ON customers (email)")
    cur.execute("CREATE INDEX orders_customer_id_idx ON orders (customer_id)")
    cur.execute("CREATE INDEX orders_ordered_at_idx ON orders (ordered_at)")

    # --- 遅いクエリ A：関数を掛けた列ではインデックスが使えず、見積もりも既定値になる ---
    cur.execute(A_BEFORE)
    before_rows = cur.fetchall()
    cur.execute(A_AFTER)
    after_rows = cur.fetchall()
    check("A: 注文履歴は 20 件", len(before_rows) == 20, str(len(before_rows)))
    check("A: 書き換え前後で結果（並びも含む）が同じ", before_rows == after_rows)
    cur.execute("SELECT count(*) FROM customers WHERE email <> lower(email)")
    check("A: 保存されているメールアドレスはすべて小文字", cur.fetchone()[0] == 0)

    plan = explain(cur, A_BEFORE)
    cust = scans_on(plan, "customers")
    check("A 改善前: customers は Seq Scan（customers_email_idx を使わない）",
          [n["Node Type"] for n in cust] == ["Seq Scan"] and "lower(email)" in cust[0].get("Filter", ""),
          str([(n["Node Type"], n.get("Filter")) for n in cust]))
    # 並列プランでは Hash の下の customers をワーカーごとに読むので、loops あたりの行数（Actual Rows）で見る
    check("A 改善前: customers の見積もりは実際の 1 行より大きく外れる（既定の選択率）",
          cust[0]["Plan Rows"] >= 100 and cust[0]["Actual Rows"] == 1,
          f"rows={cust[0]['Plan Rows']} actual={cust[0]['Actual Rows']}")
    ords = scans_on(plan, "orders")
    check("A 改善前: orders は全件を読む（orders_customer_id_idx も使わない）",
          len(ords) == 1 and ords[0]["Node Type"] in ("Seq Scan", "Parallel Seq Scan")
          and round(actual_total_rows(ords[0])) == 1_000_000, str([(n["Node Type"], actual_total_rows(n)) for n in ords]))
    check("A 改善前: 結合は Hash Join", joins(plan) == ["Hash Join"], str(joins(plan)))

    plan = explain(cur, A_AFTER)
    idx_names = {n.get("Index Name") for n in walk(plan["Plan"])}
    check("A 改善後: customers_email_idx と orders_customer_id_idx の両方を使う",
          {"customers_email_idx", "orders_customer_id_idx"} <= idx_names, str(idx_names))
    check("A 改善後: 結合は Nested Loop", joins(plan) == ["Nested Loop"], str(joins(plan)))

    cur.execute("ANALYZE customers")
    plan = explain(cur, A_BEFORE)
    check("A: ANALYZE しても関数を掛けた書き方は Seq Scan のまま（誤った改善案）",
          [n["Node Type"] for n in scans_on(plan, "customers")] == ["Seq Scan"])
    cur.execute("SELECT count(*) FROM customers c JOIN orders o ON o.customer_id = c.id "
                "WHERE c.email = 'User12345@Example.com'")
    check("A: lower() を丸ごと外すと 0 件になる（誤った書き換え）", cur.fetchone()[0] == 0)

    # --- 遅いクエリ B：統計が昨夜のままの取り込みテーブル ---
    cur.execute("""CREATE TABLE mid01_import (batch_date date NOT NULL, order_id bigint NOT NULL,
                   line_no integer NOT NULL, product_id integer NOT NULL, quantity integer NOT NULL,
                   unit_price integer NOT NULL) WITH (autovacuum_enabled = false)""")
    stale_import(cur)
    cur.execute("SELECT most_common_vals::text FROM pg_stats "
                "WHERE tablename = 'mid01_import' AND attname = 'batch_date'")
    check("B: TRUNCATE しても統計は昨夜の値（2025-12-30）のまま", cur.fetchone()[0] == "{2025-12-30}")
    cur.execute(B_QUERY)
    check("B: 重複明細は 3 行", cur.fetchone()[0] == 3)
    plan = explain(cur, B_QUERY)
    inner = [n for n in scans_on(plan, "mid01_import") if n["Actual Loops"] > 1]
    outer = [n for n in scans_on(plan, "mid01_import") if n["Actual Loops"] == 1]
    check("B 改善前: Nested Loop が選ばれる", joins(plan) == ["Nested Loop"], str(joins(plan)))
    check("B 改善前: 内側の Seq Scan を 5,481 回読み直す",
          len(inner) == 1 and inner[0]["Node Type"] == "Seq Scan" and inner[0]["Actual Loops"] == 5481,
          str([(n["Node Type"], n["Actual Loops"]) for n in inner]))
    check("B 改善前: 外側の見積もりは実際の 5,481 行より桁違いに小さい",
          len(outer) == 1 and outer[0]["Plan Rows"] * 100 < actual_total_rows(outer[0]),
          str([(n["Plan Rows"], actual_total_rows(n)) for n in outer]))

    cur.execute("VACUUM mid01_import")
    plan = explain(cur, B_QUERY)
    check("B: VACUUM だけでは Nested Loop のまま（誤った改善案）", joins(plan) == ["Nested Loop"], str(joins(plan)))

    cur.execute("ANALYZE mid01_import")
    plan = explain(cur, B_QUERY)
    check("B 改善後: ANALYZE すると Hash Join になる", joins(plan) == ["Hash Join"], str(joins(plan)))
    check("B 改善後: mid01_import は各 1 回だけ読む",
          all(n["Actual Loops"] == 1 for n in scans_on(plan, "mid01_import")))
    cur.execute(B_QUERY)
    check("B 改善後も重複明細は 3 行", cur.fetchone()[0] == 3)

    # --- 遅いクエリ C：上位 20 件のために 13 万行を全部並べる ---
    cur.execute(C_BEFORE)
    c_before = cur.fetchall()
    cur.execute(C_AFTER)
    c_after = cur.fetchall()
    check("C: 書き換え前後で 20 行が並びも含めて同じ", len(c_before) == 20 and c_before == c_after)

    plan = explain(cur, C_BEFORE)
    sorts = [n for n in find_nodes(plan, "Sort") if "ordered_at" in " ".join(n.get("Sort Key", []))]
    check("C 改善前: WindowAgg の下で pending 136,646 行を全部ソートする",
          "WindowAgg" in node_types(plan) and len(sorts) == 1
          and actual_total_rows(sorts[0]["Plans"][0]) == 136646,
          str([actual_total_rows(n["Plans"][0]) for n in sorts]))
    check("C 改善前: そのソートは外部ソート（work_mem 8MB）",
          bool(sorts) and sorts[0].get("Sort Method") == "external merge",
          str([n.get("Sort Method") for n in sorts]))

    plan = explain(cur, C_AFTER)
    back = [n for n in walk(plan["Plan"]) if n.get("Scan Direction") == "Backward"
            and n.get("Index Name") == "orders_ordered_at_idx"]
    check("C 改善後: Limit ＋ orders_ordered_at_idx の逆順走査、Sort なし",
          node_types(plan)[0] == "Limit" and bool(back) and "Sort" not in node_types(plan), str(node_types(plan)))
    check("C 改善後: インデックスから読んだのは 135 行（20 行＋フィルタで捨てた 115 行）",
          bool(back) and actual_total_rows(back[0]) + back[0].get("Rows Removed by Filter", 0) == 135,
          str([(actual_total_rows(n), n.get("Rows Removed by Filter")) for n in back]))

    cur.execute("SET work_mem = '64MB'")
    plan = explain(cur, C_BEFORE)
    sorts = [n for n in find_nodes(plan, "Sort") if "ordered_at" in " ".join(n.get("Sort Key", []))]
    check("C: work_mem を上げると quicksort になるが、全件ソートは残る（誤った改善案）",
          bool(sorts) and sorts[0].get("Sort Method") == "quicksort"
          and actual_total_rows(sorts[0]["Plans"][0]) == 136646)
    cur.execute("RESET work_mem")

    # --- 時間：改善前後を交互に 5 回ずつ（10 倍以上の差がある主張だけを判定する） ---
    for q in (A_BEFORE, A_AFTER, C_BEFORE, C_AFTER):
        exec_ms(cur, q)  # 空回し
    t: dict[str, list[float]] = {k: [] for k in ("a0", "a1", "b0", "b1", "c0", "c1")}
    for _ in range(5):
        t["a0"].append(exec_ms(cur, A_BEFORE))
        t["a1"].append(exec_ms(cur, A_AFTER))
        stale_import(cur)
        t["b0"].append(exec_ms(cur, B_QUERY))
        cur.execute("ANALYZE mid01_import")
        t["b1"].append(exec_ms(cur, B_QUERY))
        t["c0"].append(exec_ms(cur, C_BEFORE))
        t["c1"].append(exec_ms(cur, C_AFTER))
    m = {k: statistics.median(v) for k, v in t.items()}
    for q in ("a", "b", "c"):
        check(f"{q.upper()}: 改善後は改善前より 10 倍以上速い（中央値）", m[q + "0"] > 10 * m[q + "1"],
              f"{m[q + '0']:.3f} ms → {m[q + '1']:.3f} ms")
    conn.close()

    # --- MySQL：照合順序が大文字・小文字を区別しない／インデックスの無い等値結合は hash join ---
    my = mysql_connect()
    with my.cursor() as mc:
        mc.execute("CREATE INDEX customers_email_idx ON customers (email)")
        mc.execute("SELECT COUNT(*) FROM customers c JOIN orders o ON o.customer_id = c.id "
                   "WHERE c.email = 'User12345@Example.com'")
        check("MySQL: utf8mb4_0900_ai_ci では大文字を含む入力でも 20 件一致する", mc.fetchone()[0] == 20)
        mc.execute("EXPLAIN FORMAT=TREE SELECT o.id FROM customers c JOIN orders o ON o.customer_id = c.id "
                   "WHERE c.email = 'User12345@Example.com'")
        tree = mc.fetchone()[0]
        check("MySQL: そのとき customers_email_idx で 1 行を引く",
              "index lookup on c using customers_email_idx" in tree.lower(), tree.splitlines()[0])
        mc.execute("DROP TABLE IF EXISTS mid01_import")
        mc.execute("CREATE TABLE mid01_import (batch_date DATE NOT NULL, order_id BIGINT NOT NULL, "
                   "line_no INT NOT NULL, product_id INT NOT NULL)")
        mc.execute("INSERT INTO mid01_import SELECT DATE(o.ordered_at), oi.order_id, "
                   "ROW_NUMBER() OVER (PARTITION BY oi.order_id ORDER BY oi.id), oi.product_id "
                   "FROM order_items oi JOIN orders o ON o.id = oi.order_id "
                   "WHERE o.ordered_at >= '2025-12-31' AND o.ordered_at < '2026-01-01'")
        mc.execute("EXPLAIN FORMAT=TREE SELECT COUNT(*) FROM mid01_import a JOIN mid01_import b "
                   "ON b.order_id = a.order_id AND b.product_id = a.product_id AND b.line_no > a.line_no "
                   "WHERE a.batch_date = '2025-12-31' AND b.batch_date = '2025-12-31'")
        tree = mc.fetchone()[0]
        check("MySQL: 取り込みテーブルの自己結合は hash join", "hash join" in tree.lower())
        mc.execute("DROP TABLE mid01_import")
    my.close()

    finish("Mid01 遅いクエリを速くする")


if __name__ == "__main__":
    main()

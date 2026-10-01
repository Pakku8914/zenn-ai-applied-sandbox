"""Review01 横断復習①（S02〜S05）の自己検証。

練習問題の正解として使う物理量（ページ数・木の高さ・loops・Heap Fetches など）が出発点から再現できることを確かめる。
出発点（tools/reset.sh 直後）から単独で実行して成功すること。
"""

from __future__ import annotations

import math

from labcheck import (actual_total_rows, check, explain, find_nodes, finish,
                      node_types, pg_connect)

PAGE, HEADER, LINE_POINTER = 8192, 24, 4


def maxalign(n: int) -> int:
    return (n + 7) // 8 * 8


def verify_pg() -> None:
    conn = pg_connect()
    cur = conn.cursor()

    # --- R1/R2: ページ数の見積もり（01） ---
    cur.execute("SELECT relname, relpages, reltuples FROM pg_class WHERE relname IN ('customers', 'order_items')")
    rel = {name: (pages, tuples) for name, pages, tuples in cur.fetchall()}
    cur.execute("SELECT count(*), max(lp_len) FROM heap_page_items(get_raw_page('customers', 0))")
    n0, max_len = cur.fetchone()
    check("R1 customers の 0 ページ目は 104 行・最長のタプルは 80 バイト", (n0, max_len) == (104, 80), f"{n0} 行 / {max_len}")
    per_page = (PAGE - HEADER) // (maxalign(80) + LINE_POINTER)
    pages = math.ceil(50000 / per_page)
    check("R1 80 バイトのタプルで見積もると 1 ページ 97 行・516 ページ", (per_page, pages) == (97, 516),
          f"{per_page} 行/ページ・{pages} ページ")
    check("R1 customers の実際のページ数は 516", rel["customers"][0] == 516, str(rel["customers"][0]))
    cur.execute("SELECT count(*), min(lp_len), max(lp_len) FROM heap_page_items(get_raw_page('order_items', 0))")
    n0, mn, mx = cur.fetchone()
    check("R2 order_items の 0 ページ目は 136 行・タプルはすべて 52 バイト", (n0, mn, mx) == (136, 52, 52))
    per_page = (PAGE - HEADER) // (maxalign(52) + LINE_POINTER)
    pages = math.ceil(2_000_000 / per_page)
    check("R2 見積もり（1 ページ 136 行・14,706 ページ）が実際のページ数と一致", (per_page, pages) == (136, 14706)
          and rel["order_items"][0] == 14706, f"{per_page} 行/ページ・{pages} ページ / 実際 {rel['order_items'][0]}")

    # --- R3: 主キーで 1 行を引くときに読むページ数と木の高さ（02） ---
    for table, index, key, level in (("customers", "customers_pkey", 12345, 1), ("orders", "orders_pkey", 123456, 2)):
        cur.execute(f"SELECT level FROM bt_metap('{index}')")
        got_level = cur.fetchone()[0]
        check(f"R3 {index} の level は {level}", got_level == level, str(got_level))
        # 接続して最初の実行は、比較関数などのカタログ読み込みがノードのバッファ数に混ざることがあるので 2 回目で判定する
        explain(cur, f"SELECT * FROM {table} WHERE id = {key}", buffers=True)
        p = explain(cur, f"SELECT * FROM {table} WHERE id = {key}", buffers=True)
        node = find_nodes(p, "Index Scan")[0]
        touched = node["Shared Hit Blocks"] + node["Shared Read Blocks"]
        check(f"R3 {table} の 1 行検索で読むページ数 = 木の段数（level + 1）+ ヒープ 1", touched == level + 2,
              f"{touched} ページ")

    # --- R10: Seq Scan のコストの分解（03） ---
    cur.execute("SELECT relname, relpages, reltuples FROM pg_class WHERE relname IN ('products', 'customers', 'orders')")
    rel = {name: (pages, tuples) for name, pages, tuples in cur.fetchall()}
    cur.execute("SET max_parallel_workers_per_gather = 0")
    for table, cond, n_ops in (("products", "category = '文具'", 1),
                               ("customers", "region = '東京' OR region = '大阪'", 2),
                               ("orders", "customer_id = 777", 1)):
        pages, tuples = rel[table]
        want = pages * 1.0 + tuples * 0.01 + tuples * 0.0025 * n_ops
        p = explain(cur, f"SELECT * FROM {table} WHERE {cond}", analyze=False)
        got = p["Plan"]["Total Cost"]
        check(f"R10 {table} の Seq Scan のコスト = ページ数 + 行数 × 0.01 + 行数 × 0.0025 × {n_ops}",
              p["Plan"]["Node Type"] == "Seq Scan" and abs(got - want) < 0.01, f"{got} / 計算 {want}")
    cur.execute("RESET ALL")

    # --- R4: 並列実行の rows と loops（04） ---
    p = explain(cur, "SELECT * FROM orders WHERE customer_id = 777")
    gather = find_nodes(p, "Gather")
    scan = find_nodes(p, "Seq Scan")[0]
    check("R4 Gather が返した行数は 20", bool(gather) and actual_total_rows(gather[0]) == 20)
    check("R4 ワーカー数の計画は 2（リーダーと合わせて 3 プロセス）", bool(gather) and gather[0]["Workers Planned"] == 2)
    removed = scan["Rows Removed by Filter"] * scan["Actual Loops"]
    check("R4 3 プロセス合計で読んだ行数（返した + 捨てた）は約 100 万", abs(removed + 20 - 1_000_000) < 10,
          f"{removed:.0f} + 20")

    # --- R5: SubPlan の loops（05） ---
    p = explain(cur, "SELECT c.id, c.name, (SELECT count(*) FROM orders o WHERE o.customer_id = c.id) AS n "
                     "FROM customers c WHERE c.id <= 5")
    scans = [n for n in find_nodes(p, "Seq Scan") if n.get("Relation Name") == "orders"]
    check("R5 相関サブクエリの中の orders の Seq Scan は 5 回（loops=5）実行される",
          bool(scans) and scans[0]["Actual Loops"] == 5, str(node_types(p)))
    if scans:
        check("R5 1 回あたり 20 行を返し 999,980 行を捨てる",
              scans[0]["Actual Rows"] == 20 and scans[0]["Rows Removed by Filter"] == 999980)
    p = explain(cur, "SELECT c.id, c.name, count(o.id) FROM customers c LEFT JOIN orders o ON o.customer_id = c.id "
                     "WHERE c.id <= 5 GROUP BY c.id, c.name ORDER BY c.id")
    scans = [n for n in find_nodes(p, "Seq Scan") if n.get("Relation Name") == "orders"]
    check("R5 結合と集約に書き換えると orders を 1 回だけ読む", len(scans) == 1 and scans[0]["Actual Loops"] == 1,
          str(node_types(p)))
    cur.execute("CREATE INDEX orders_customer_id_idx ON orders (customer_id)")
    p = explain(cur, "SELECT c.id, c.name, (SELECT count(*) FROM orders o WHERE o.customer_id = c.id) AS n "
                     "FROM customers c WHERE c.id <= 5")
    ios = [n for n in find_nodes(p, "Index Only Scan") if n.get("Relation Name") == "orders"]
    check("R5 customer_id にインデックスを作ると SubPlan は Index Only Scan を 5 回",
          len(ios) == 1 and ios[0]["Actual Loops"] == 5 and ios[0]["Actual Rows"] == 20, str(node_types(p)))
    cur.execute("DROP INDEX orders_customer_id_idx")

    # --- R6: 同じ 2,740 行で読むページ数が違う（06） ---
    cur.execute("CREATE INDEX orders_ordered_at_idx ON orders (ordered_at)")
    p = explain(cur, "SELECT * FROM orders WHERE ordered_at >= '2025-06-01' AND ordered_at < '2025-06-02'")
    bhs = find_nodes(p, "Bitmap Heap Scan")
    check("R6 1 日分（2,740 行）は Bitmap Heap Scan で 2,740 ページを読む",
          bool(bhs) and bhs[0]["Exact Heap Blocks"] == 2740 and actual_total_rows(bhs[0]) == 2740)
    p = explain(cur, "SELECT * FROM orders WHERE id BETWEEN 100001 AND 102740")
    check("R6 id の範囲（2,740 行）は Index Scan", p["Plan"]["Node Type"] == "Index Scan"
          and actual_total_rows(p["Plan"]) == 2740, p["Plan"]["Node Type"])
    cur.execute("SELECT count(DISTINCT (ctid::text::point)[0]) FROM orders WHERE id BETWEEN 100001 AND 102740")
    check("R6 id の範囲の 2,740 行は 24 ページに収まっている", cur.fetchone()[0] == 24)

    # --- R7/R8: UPDATE と ctid・Heap Fetches（07） ---
    cur.execute("CREATE TABLE r01_customers WITH (autovacuum_enabled = false) AS SELECT * FROM customers")
    cur.execute("CREATE INDEX r01_customers_id_idx ON r01_customers (id)")
    cur.execute("VACUUM (ANALYZE) r01_customers")
    q = "SELECT count(*) FROM r01_customers WHERE id <= 1000"

    def heap_fetches() -> int:
        return find_nodes(explain(cur, q), "Index Only Scan")[0]["Heap Fetches"]

    cur.execute("SELECT ctid::text FROM r01_customers WHERE id = 500")
    before = cur.fetchone()[0]
    check("R8 id = 500 は最初 (5,8) にある", before == "(5,8)", before)
    check("R7 VACUUM 直後の Heap Fetches は 0", heap_fetches() == 0)
    cur.execute("UPDATE r01_customers SET name = name WHERE id = 500")
    cur.execute("SELECT ctid::text FROM r01_customers WHERE id = 500")
    after = cur.fetchone()[0]
    check("R8 UPDATE 後の新しい版は最終ページ（515）へ移る", after.startswith("(515,"), after)
    hf = heap_fetches()
    check("R7 1 行の UPDATE で Heap Fetches が数十〜百に増える（ページ単位で all-visible が落ちるため）", 50 < hf < 200,
          str(hf))
    cur.execute("VACUUM r01_customers")
    hf = heap_fetches()
    check("R7 不要行が 1 つだけだと VACUUM はインデックスの掃除を省略し、Heap Fetches が残る", hf > 0, str(hf))
    cur.execute("VACUUM (INDEX_CLEANUP ON) r01_customers")
    check("R7 VACUUM (INDEX_CLEANUP ON) で Heap Fetches が 0 に戻る", heap_fetches() == 0)

    # --- R9: 見積もりのズレ（08） ---
    p = explain(cur, "SELECT * FROM orders WHERE ordered_at::date = '2025-06-01'")
    check("R9 ::date の条件はインデックスを使わない",
          not any("Index" in t for t in node_types(p)), str(node_types(p)))
    check("R9 ::date の条件は 5,000 行（0.5%）と見積もられ、実際は 2,740 行",
          p["Plan"]["Plan Rows"] == 5000 and actual_total_rows(p["Plan"]) == 2740, str(p["Plan"]["Plan Rows"]))

    # --- R11: 20% しか返さない Bitmap が全ページを読む（09） ---
    cur.execute("CREATE INDEX customers_region_idx ON customers (region)")
    p = explain(cur, "SELECT * FROM customers WHERE region = '札幌'")
    bhs = find_nodes(p, "Bitmap Heap Scan")
    check("R11 札幌（10,000 行）の Bitmap Heap Scan は 516 ページすべてを読む",
          bool(bhs) and bhs[0]["Exact Heap Blocks"] == 516 and actual_total_rows(bhs[0]) == 10000)
    cur.execute("SELECT count(*) FILTER (WHERE region = '札幌'), count(*) FROM customers WHERE (ctid::text::point)[0] = 0")
    check("R11 0 ページ目の 104 行のうち 21 行が札幌", cur.fetchone() == (21, 104))
    conn.close()


if __name__ == "__main__":
    verify_pg()
    finish("Review01 横断復習①")

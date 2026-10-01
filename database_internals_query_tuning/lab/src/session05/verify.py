"""S05 スキャン方式とアクセスパス の自己検証。

出発点（tools/reset.sh 直後）から単独で実行して成功すること。
判定はノードの種類・実測行数・Heap Fetches・Exact/Lossy Heap Blocks・Workers Planned だけで行い、
見積もりの rows / cost と実行時間は使わない（ANALYZE の標本抽出と環境で揺れるため）。
"""

from __future__ import annotations

from labcheck import (actual_total_rows, check, explain, find_nodes, finish,
                      mysql_connect, node_types, pg_connect)

DAY = "ordered_at >= '2025-06-01' AND ordered_at < '2025-06-02'"
WEEK = "ordered_at >= '2025-06-01' AND ordered_at < '2025-06-08'"


def uses_index(plan: dict) -> bool:
    return any(t in ("Index Scan", "Index Only Scan", "Bitmap Index Scan") for t in node_types(plan))


def top_scan(plan: dict) -> str:
    """Gather の下にあるスキャンも含め、最上位のスキャン系ノードの名前（並列なら Parallel を付ける）。"""
    for t in node_types(plan):
        if "Scan" in t:
            nodes = find_nodes(plan, t)
            return ("Parallel " if nodes[0].get("Parallel Aware") else "") + t
    return ""


def verify_pg() -> None:
    conn = pg_connect()
    cur = conn.cursor()

    cur.execute("CREATE INDEX customers_region_idx ON customers (region)")
    cur.execute("CREATE INDEX orders_ordered_at_idx ON orders (ordered_at)")

    # --- 4 つのスキャン方式（02_four_scan_methods.sql） ---
    p = explain(cur, "SELECT * FROM products WHERE category = '文具'")
    check("E2 インデックスのない列で絞ると Seq Scan", top_scan(p) == "Seq Scan", top_scan(p))
    check("E2 products の文具は 1,250 行", actual_total_rows(p["Plan"]) == 1250)

    p = explain(cur, "SELECT * FROM customers WHERE id = 12345")
    check("E2 主キーで 1 行なら Index Scan", top_scan(p) == "Index Scan", top_scan(p))

    p = explain(cur, f"SELECT count(*) FROM orders WHERE {DAY}")
    ios = find_nodes(p, "Index Only Scan")
    check("E2 ordered_at だけで答えが出るなら Index Only Scan", len(ios) == 1, str(node_types(p)))
    if ios:
        check("E2 VACUUM 済みなので Heap Fetches は 0", ios[0]["Heap Fetches"] == 0, str(ios[0]["Heap Fetches"]))
        check("E2 1 日分は 2,740 行", actual_total_rows(ios[0]) == 2740)

    p = explain(cur, f"SELECT * FROM orders WHERE {DAY}")
    check("E2 同じ範囲で全列を取ると Bitmap Heap Scan", top_scan(p) == "Bitmap Heap Scan", top_scan(p))
    bhs = find_nodes(p, "Bitmap Heap Scan")
    if bhs:
        check("E2 1 日分の 2,740 行は 2,740 ページに 1 行ずつ散らばる", bhs[0]["Exact Heap Blocks"] == 2740,
              str(bhs[0]["Exact Heap Blocks"]))

    # --- 選択率（03_selectivity_region_vs_id.sql） ---
    cur.execute("SELECT relpages FROM pg_class WHERE relname = 'customers'")
    customers_pages = cur.fetchone()[0]
    p = explain(cur, "SELECT * FROM customers WHERE region = '東京'")
    bhs = find_nodes(p, "Bitmap Heap Scan")
    check("E3 選択率 20% の region は Bitmap Heap Scan（Seq Scan ではない）", len(bhs) == 1, top_scan(p))
    if bhs:
        check("E3 東京は 10,000 行", actual_total_rows(bhs[0]) == 10000)
        check("E3 Bitmap でも全ページ（customers の relpages）を読む", bhs[0]["Exact Heap Blocks"] == customers_pages,
              f'{bhs[0]["Exact Heap Blocks"]} / {customers_pages}')
    p = explain(cur, "SELECT * FROM customers WHERE region IN ('東京', '大阪')", analyze=False)
    check("E3 選択率 40% でもまだ Bitmap Heap Scan", top_scan(p) == "Bitmap Heap Scan", top_scan(p))
    p = explain(cur, "SELECT * FROM customers WHERE region IN ('東京', '大阪', '名古屋')", analyze=False)
    check("E3 選択率 60% で Seq Scan に切り替わる", top_scan(p) == "Seq Scan", top_scan(p))

    # --- 境界（04・05）。境界から十分に離れた値だけで判定する ---
    p = explain(cur, "SELECT * FROM orders WHERE id BETWEEN 1 AND 500000", analyze=False)
    check("E4 相関ありの id は 50 万行でも Index Scan", top_scan(p) == "Index Scan", top_scan(p))
    p = explain(cur, "SELECT * FROM orders WHERE id BETWEEN 1 AND 700000", analyze=False)
    check("E4 id 70 万行では Seq Scan", top_scan(p) == "Seq Scan", top_scan(p))
    p = explain(cur, "SELECT * FROM orders WHERE ordered_at >= '2025-06-01 00:00:00' "
                     "AND ordered_at < '2025-06-01 00:01:00'", analyze=False)
    check("E5 相関なしの ordered_at は 60 秒分（数行）なら Index Scan", top_scan(p) == "Index Scan", top_scan(p))
    p = explain(cur, "SELECT * FROM orders WHERE ordered_at >= '2025-06-01 00:00:00' "
                     "AND ordered_at < '2025-06-01 00:05:00'", analyze=False)
    check("E5 300 秒分（約 10 行）でもう Bitmap Heap Scan", top_scan(p) == "Bitmap Heap Scan", top_scan(p))
    p = explain(cur, "SELECT * FROM orders WHERE ordered_at >= '2025-01-01' AND ordered_at < '2025-01-31'",
                analyze=False)
    check("E5 30 日分は Bitmap Heap Scan", top_scan(p) == "Bitmap Heap Scan", top_scan(p))
    p = explain(cur, "SELECT * FROM orders WHERE ordered_at >= '2025-01-01' AND ordered_at < '2025-06-30'",
                analyze=False)
    check("E5 180 日分は Seq Scan", top_scan(p) == "Seq Scan", top_scan(p))
    cur.execute("SET enable_bitmapscan = off")
    p = explain(cur, f"SELECT * FROM orders WHERE {DAY}", analyze=False)
    check("E5 Bitmap 禁止: 1 日分は Index Scan", top_scan(p) == "Index Scan", top_scan(p))
    p = explain(cur, "SELECT * FROM orders WHERE ordered_at >= '2025-06-01' AND ordered_at < '2025-06-04'",
                analyze=False)
    check("E5 Bitmap 禁止: 3 日分で Parallel Seq Scan に負ける", top_scan(p) == "Parallel Seq Scan", top_scan(p))
    cur.execute("RESET ALL")

    # --- Bitmap はページ単位・物理順に読み直す（06） ---
    cur.execute(f"SELECT count(*), count(DISTINCT (ctid::text::point)[0]) FROM orders WHERE {WEEK}")
    rows, pages = cur.fetchone()
    check("E6 1 週間分は 19,180 行・2,878 ページ", (rows, pages) == (19180, 2878), f"{rows} 行 / {pages} ページ")
    p = explain(cur, f"SELECT * FROM orders WHERE {WEEK}", buffers=True)
    bhs = find_nodes(p, "Bitmap Heap Scan")
    check("E6 1 週間はプランナが Bitmap Heap Scan を選ぶ", len(bhs) == 1, top_scan(p))
    if bhs:
        check("E6 Bitmap は各ページを 1 回だけ読む（exact = ページ数）", bhs[0]["Exact Heap Blocks"] == pages)
    cur.execute("SET enable_bitmapscan = off")
    cur.execute("SET enable_seqscan = off")
    p = explain(cur, f"SELECT * FROM orders WHERE {WEEK}", buffers=True)
    ixs = find_nodes(p, "Index Scan")
    check("E6 強制すると Index Scan", len(ixs) == 1, top_scan(p))
    if ixs:
        touched = ixs[0]["Shared Hit Blocks"] + ixs[0]["Shared Read Blocks"]
        check("E6 Index Scan は同じページを何度も読む（バッファ参照 > ページ数の 5 倍）", touched > pages * 5,
              f"{touched} 回")
    cur.execute("RESET ALL")

    # --- Index Only Scan と Visibility Map（07。作業用コピーで行う） ---
    cur.execute("CREATE EXTENSION IF NOT EXISTS pg_visibility")
    cur.execute("CREATE TABLE s05_orders WITH (autovacuum_enabled = false) AS SELECT * FROM orders")
    cur.execute("CREATE INDEX s05_orders_ordered_at_idx ON s05_orders (ordered_at)")
    cur.execute("VACUUM (ANALYZE) s05_orders")
    q = f"SELECT count(*) FROM s05_orders WHERE {DAY}"

    def heap_fetches() -> int | None:
        nodes = find_nodes(explain(cur, q), "Index Only Scan")
        return nodes[0]["Heap Fetches"] if nodes else None

    def all_visible() -> int:
        cur.execute("SELECT all_visible FROM pg_visibility_map_summary('s05_orders')")
        return cur.fetchone()[0]

    av_before = all_visible()
    check("E7 VACUUM 直後の Index Only Scan は Heap Fetches 0", heap_fetches() == 0)
    with conn.transaction(force_rollback=True):
        cur.execute(f"UPDATE s05_orders SET status = status WHERE {DAY}")
    # 旧版のある 2,740 ページ＋新版を書き込んだ末尾のページの all-visible が落ちる
    av_after = all_visible()
    check("E7 UPDATE → ROLLBACK で 2,740 ページ以上の all-visible が落ちる", av_before - av_after >= 2740,
          f"{av_before} → {av_after}")
    hf = heap_fetches()
    check("E7 ROLLBACK 後は Heap Fetches が増える", hf is not None and hf > 0, str(hf))
    cur.execute("VACUUM (INDEX_CLEANUP ON) s05_orders")
    check("E7 VACUUM (INDEX_CLEANUP ON) で Heap Fetches 0 に戻る", heap_fetches() == 0)

    # --- lossy ビットマップ（08） ---
    cur.execute("SET max_parallel_workers_per_gather = 0")
    p = explain(cur, f"SELECT * FROM orders WHERE {WEEK}")
    bhs = find_nodes(p, "Bitmap Heap Scan")
    check("E8 work_mem 8MB では lossy なし", bool(bhs) and bhs[0]["Lossy Heap Blocks"] == 0)
    cur.execute("SET work_mem = '64kB'")
    p = explain(cur, f"SELECT * FROM orders WHERE {WEEK}")
    bhs = find_nodes(p, "Bitmap Heap Scan")
    check("E8 work_mem 64kB では lossy ページが出る", bool(bhs) and bhs[0]["Lossy Heap Blocks"] > 0,
          str(bhs[0]["Lossy Heap Blocks"]) if bhs else top_scan(p))
    if bhs:
        check("E8 lossy ページでは Recheck で行が捨てられる", bhs[0].get("Rows Removed by Index Recheck", 0) > 0)
        check("E8 lossy でも結果は 19,180 行", actual_total_rows(bhs[0]) == 19180)
    cur.execute("RESET ALL")

    # --- インデックスが使われないケース（09） ---
    cur.execute("CREATE INDEX customers_email_idx ON customers (email)")
    cur.execute("CREATE INDEX orders_status_idx ON orders (status)")
    cases = [
        ("E9 email = ... は使われる", "SELECT * FROM customers WHERE email = 'user123@example.com'", True),
        ("E9 lower(email) = ... は使われない", "SELECT * FROM customers WHERE lower(email) = 'user123@example.com'", False),
        ("E9 ordered_at::date = ... は使われない", "SELECT * FROM orders WHERE ordered_at::date = '2025-06-01'", False),
        ("E9 範囲に書き換えると使われる", f"SELECT * FROM orders WHERE {DAY}", True),
        ("E9 integer の列を numeric と比べると使われない", "SELECT * FROM customers WHERE id = 12345.0", False),
        ("E9 文字列リテラル '12345' なら使われる", "SELECT * FROM customers WHERE id = '12345'", True),
        ("E9 bigint の列を integer と比べるのは使われる", "SELECT * FROM orders WHERE id = 12345::integer", True),
        ("E9 前方一致 LIKE は使われる（照合順序 C）", "SELECT * FROM customers WHERE email LIKE 'user123%'", True),
        ("E9 後方一致 LIKE は使われない", "SELECT * FROM customers WHERE email LIKE '%123@example.com'", False),
        ("E9 status <> 'completed' は使われない", "SELECT * FROM orders WHERE status <> 'completed'", False),
        ("E9 status IN (...) に書き換えると使われる",
         "SELECT * FROM orders WHERE status IN ('pending', 'cancelled')", True),
        ("E9 OR の両側にインデックスがあれば使われる（BitmapOr）",
         "SELECT * FROM orders WHERE (ordered_at >= '2025-06-01' AND ordered_at < '2025-06-01 01:00') OR id = 777", True),
        ("E9 OR の片側（customer_id）にインデックスがなければ使われない",
         "SELECT * FROM orders WHERE (ordered_at >= '2025-06-01' AND ordered_at < '2025-06-01 01:00') "
         "OR customer_id = 777", False),
    ]
    for name, sql, want in cases:
        p = explain(cur, sql, analyze=False)
        check(name, uses_index(p) == want, str(node_types(p)))
    p = explain(cur, "SELECT * FROM orders WHERE (ordered_at >= '2025-06-01' AND ordered_at < '2025-06-01 01:00') "
                     "OR id = 777", analyze=False)
    check("E9 OR の両側は BitmapOr で合成される", "BitmapOr" in node_types(p))
    cur.execute("SELECT count(*) FROM orders WHERE status <> 'completed'")
    ne = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM orders WHERE status IN ('pending', 'cancelled')")
    check("E9 <> と IN の書き換えで件数が同じ", ne == cur.fetchone()[0], str(ne))
    cur.execute("CREATE INDEX customers_lower_email_idx ON customers (lower(email))")
    cur.execute("ANALYZE customers")
    p = explain(cur, "SELECT * FROM customers WHERE lower(email) = 'user123@example.com'", analyze=False)
    check("E9 式インデックスを作ると lower(email) でも使われる", uses_index(p), str(node_types(p)))

    # --- 並列スキャン（10） ---
    p = explain(cur, "SELECT count(*) FROM orders WHERE customer_id = 777")
    g = find_nodes(p, "Gather")
    check("E10 orders は Parallel Seq Scan", top_scan(p) == "Parallel Seq Scan", top_scan(p))
    check("E10 customer_id = 777 は 20 行", round(actual_total_rows(find_nodes(p, "Seq Scan")[0])) == 20)
    check("E10 orders の Workers Planned は 2", bool(g) and g[0]["Workers Planned"] == 2)
    p = explain(cur, "SELECT count(*) FROM products WHERE price > 5000")
    check("E10 products（小さい）は並列にならない", not find_nodes(p, "Gather"), str(node_types(p)))
    cur.execute("SET min_parallel_table_scan_size = 0")
    p = explain(cur, "SELECT count(*) FROM products WHERE price > 5000", analyze=False)
    check("E10 下限を 0 にしても起動コストに見合わず並列にならない", not find_nodes(p, "Gather"))
    cur.execute("SET parallel_setup_cost = 0")
    cur.execute("SET parallel_tuple_cost = 0")
    p = explain(cur, "SELECT count(*) FROM products WHERE price > 5000", analyze=False)
    check("E10 起動コストも 0 にすると並列になる", bool(find_nodes(p, "Gather")))
    cur.execute("RESET ALL")
    cur.execute("SET max_parallel_workers_per_gather = 0")
    p = explain(cur, "SELECT count(*) FROM orders WHERE customer_id = 777", analyze=False)
    check("E10 max_parallel_workers_per_gather = 0 で並列が止まる", top_scan(p) == "Seq Scan", top_scan(p))
    cur.execute("SET max_parallel_workers_per_gather = 4")
    for table, cond, want in (("orders", "customer_id = 777", 2), ("order_items", "product_id = 777", 3)):
        p = explain(cur, f"SELECT count(*) FROM {table} WHERE {cond}", analyze=False)
        g = find_nodes(p, "Gather")
        got = g[0]["Workers Planned"] if g else None
        check(f"E10 上限 4 でも {table} の Workers Planned は {want}（大きさで決まる）", got == want, str(got))
    cur.execute("RESET ALL")
    conn.close()


def verify_mysql() -> None:
    conn = mysql_connect()
    try:
        with conn.cursor() as cur:
            for table, index, col in (("customers", "customers_region_idx", "region"),
                                      ("orders", "orders_ordered_at_idx", "ordered_at")):
                cur.execute("SELECT count(*) FROM information_schema.statistics WHERE table_schema = DATABASE() "
                            "AND table_name = %s AND index_name = %s", (table, index))
                if cur.fetchone()[0] == 0:
                    cur.execute(f"CREATE INDEX {index} ON {table} ({col})")

            def row(sql: str) -> dict:
                cur.execute("EXPLAIN FORMAT=TRADITIONAL " + sql)
                cols = [d[0] for d in cur.description]
                return dict(zip(cols, cur.fetchone()))

            cases = [
                ("SELECT * FROM customers WHERE id = 12345", "const"),
                ("SELECT * FROM customers WHERE region = '東京'", "ref"),
                (f"SELECT * FROM orders WHERE {DAY}", "range"),
                ("SELECT * FROM products WHERE category = '文具'", "ALL"),
                ("SELECT count(*) FROM customers", "index"),
            ]
            for sql, want in cases:
                r = row(sql)
                check(f"MySQL type={want}: {sql[:48]}", r["type"] == want, str(r["type"]))
            r = row("SELECT id FROM customers WHERE region = '東京'")
            check("MySQL セカンダリインデックスは主キーを持つので id だけならカバリング",
                  "Using index" in (r["Extra"] or ""), str(r["Extra"]))
            r = row("SELECT count(*) FROM orders WHERE customer_id = 777")
            check("MySQL 外部キーのインデックスが自動で作られていて使われる", r["key"] == "fk_orders_customer", str(r["key"]))
            cur.execute(f"EXPLAIN ANALYZE SELECT count(*) FROM orders WHERE {DAY}")
            tree = cur.fetchone()[0]
            check("MySQL 件数だけなら Covering index range scan", "Covering index range scan" in tree)
            cur.execute(f"SELECT count(*) FROM orders WHERE {DAY}")
            check("MySQL 1 日分は 2,740 行", cur.fetchone()[0] == 2740)
    finally:
        conn.close()


if __name__ == "__main__":
    verify_pg()
    verify_mysql()
    finish("S05 スキャン方式とアクセスパス")

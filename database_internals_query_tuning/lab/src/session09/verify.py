"""S09 インデックス設計の実践 — 自己検証。

出発点（tools/reset.sh 直後）から単独で実行する。章の SQL と同じインデックス・作業用テーブルを自分で作る。
判定に使うのはノードの種類・実測の行数・クエリの結果・インデックスの大きさ（物理量）・Heap Fetches・
HOT 更新の件数と、差の大きい量（読んだページの合計・時間）の大小だけ。
"""

from __future__ import annotations

import statistics
import time

import psycopg

from labcheck import (actual_total_rows, check, explain, find_nodes, finish,
                      mysql_connect, node_types, walk)

PENDING_WEEK = """
SELECT id, customer_id, ordered_at FROM orders
WHERE status = 'pending' AND ordered_at >= '2025-06-01' AND ordered_at < '2025-06-08'
"""
PENDING_JUNE_COUNT = """
SELECT count(*) FROM orders
WHERE status = 'pending' AND ordered_at >= '2025-06-01' AND ordered_at < '2025-07-01'
"""
DAY_COUNT = "SELECT count(*) FROM orders WHERE ordered_at >= '2025-06-01' AND ordered_at < '2025-06-02'"
CUSTOMER_ORDERS = "SELECT id, ordered_at, status FROM {t} WHERE customer_id = 12345 ORDER BY ordered_at DESC"
A_AFTER = """
SELECT o.id, o.ordered_at, o.status
FROM customers c JOIN orders o ON o.customer_id = c.id
WHERE c.email = lower('User12345@Example.com')
ORDER BY o.ordered_at DESC
"""
A_BEFORE = A_AFTER.replace("c.email = lower(", "lower(c.email) = lower(")
C_AFTER = "SELECT id, customer_id, ordered_at FROM orders WHERE status = 'pending' ORDER BY ordered_at DESC LIMIT 20"
C_BEFORE = """
SELECT id, customer_id, ordered_at
FROM (SELECT id, customer_id, ordered_at, row_number() OVER (ORDER BY ordered_at DESC) AS rn
      FROM orders WHERE status = 'pending') t
WHERE rn <= 20 ORDER BY rn
"""
FLIP = ("UPDATE {t} SET status = CASE WHEN status = 'completed' THEN 'pending' ELSE 'completed' END "
        "WHERE id % 10 = 0")


def buffers(plan: dict) -> int:
    p = plan["Plan"]
    return p.get("Shared Hit Blocks", 0) + p.get("Shared Read Blocks", 0)


def index_names(plan: dict) -> set[str]:
    return {n["Index Name"] for n in walk(plan["Plan"]) if "Index Name" in n}


def nodes_on(plan: dict, relation: str) -> list[dict]:
    return [n for n in walk(plan["Plan"]) if n.get("Relation Name") == relation]


def size(cur, rel: str) -> int:
    cur.execute("SELECT pg_relation_size(%s::regclass)", (rel,))
    return cur.fetchone()[0]


def exec_ms(cur, sql: str) -> float:
    cur.execute("EXPLAIN (ANALYZE, TIMING OFF, FORMAT JSON) " + sql)
    return cur.fetchone()[0][0]["Execution Time"]


def flush(cur) -> None:
    cur.execute("SELECT pg_stat_force_next_flush()")
    time.sleep(1.1)


def idx_scan(cur, name: str) -> int:
    cur.execute("SELECT idx_scan FROM pg_stat_user_indexes WHERE indexrelname = %s", (name,))
    return cur.fetchone()[0]


def main() -> None:
    conn = psycopg.connect(autocommit=True, prepare_threshold=None)
    cur = conn.cursor()

    # --- E1: 複合インデックスの列順 ---
    cur.execute("CREATE INDEX orders_ordered_at_idx ON orders (ordered_at)")
    plan = explain(cur, PENDING_WEEK, buffers=True)
    heap = find_nodes(plan, "Bitmap Heap Scan")
    check("E1 単一列: status はヒープで Filter（16,559 行を捨てる）",
          bool(heap) and "status" in heap[0].get("Filter", "") and heap[0].get("Rows Removed by Filter") == 16559,
          str([(n.get("Filter"), n.get("Rows Removed by Filter")) for n in heap]))
    single_june = explain(cur, PENDING_JUNE_COUNT, buffers=True)
    cur.execute("CREATE INDEX orders_status_ordered_at_idx ON orders (status, ordered_at)")
    plan = explain(cur, PENDING_WEEK, buffers=True)
    bis = find_nodes(plan, "Bitmap Index Scan")
    heap = find_nodes(plan, "Bitmap Heap Scan")
    check("E1 (status, ordered_at): status も Index Cond に入り、Filter が消える",
          bool(bis) and "status" in bis[0].get("Index Cond", "") and "Filter" not in heap[0]
          and heap[0].get("Exact Heap Blocks") == 2621,
          str([(n.get("Index Name"), n.get("Exact Heap Blocks")) for n in bis + heap]))
    eq_first = explain(cur, PENDING_JUNE_COUNT, buffers=True)
    check("E1 (status, ordered_at): 6 月の件数は Index Only Scan",
          "Index Only Scan" in node_types(eq_first) and actual_total_rows(eq_first["Plan"]["Plans"][0]) == 11232)
    cur.execute("DROP INDEX orders_status_ordered_at_idx")
    cur.execute("CREATE INDEX orders_ordered_at_status_idx ON orders (ordered_at, status)")
    range_first = explain(cur, PENDING_JUNE_COUNT, buffers=True)
    check("E1 (ordered_at, status) も Index Only Scan", "orders_ordered_at_status_idx" in index_names(range_first))
    check("E1 範囲の列が先だと、読むページが等値の列が先の 4 倍以上",
          buffers(range_first) > 4 * buffers(eq_first), f"{buffers(range_first)} / {buffers(eq_first)}")
    check("E1 単一列（ヒープで Filter）は複合インデックス（等値が先）の 20 倍以上のページを読む",
          buffers(single_june) > 20 * buffers(eq_first), f"{buffers(single_june)} / {buffers(eq_first)}")
    cur.execute("CREATE INDEX orders_status_ordered_at_idx ON orders (status, ordered_at)")
    check("E1 複合インデックスは単一列の 1.5 倍以上の大きさ",
          size(cur, "orders_status_ordered_at_idx") > 1.5 * size(cur, "orders_ordered_at_idx"))
    cur.execute("DROP INDEX orders_ordered_at_idx, orders_status_ordered_at_idx, orders_ordered_at_status_idx")

    # --- E2: スキップスキャン ---
    cur.execute("CREATE INDEX orders_status_ordered_at_idx ON orders (status, ordered_at)")
    plan = explain(cur, DAY_COUNT)
    ios = find_nodes(plan, "Index Only Scan")
    check("E2 (status, ordered_at) だけで ordered_at を絞ると、スキップスキャン（Index Searches: 7）",
          bool(ios) and ios[0].get("Index Searches") == 7 and actual_total_rows(ios[0]) == 2740,
          str([n.get("Index Searches") for n in ios]))
    cur.execute("DROP INDEX orders_status_ordered_at_idx")
    cur.execute("CREATE INDEX orders_customer_id_ordered_at_idx ON orders (customer_id, ordered_at)")
    plan = explain(cur, DAY_COUNT)
    check("E2 先頭列の種類が多い (customer_id, ordered_at) はプランナが使わない",
          "orders_customer_id_ordered_at_idx" not in index_names(plan), str(node_types(plan)))
    cur.execute("SET enable_seqscan = off")
    plan = explain(cur, DAY_COUNT)
    ios = find_nodes(plan, "Index Only Scan")
    check("E2 強制すると、飛ばし読みせずに全体を読む（Index Searches: 1）",
          bool(ios) and ios[0].get("Index Searches") == 1, str([n.get("Index Searches") for n in ios]))
    cur.execute("RESET enable_seqscan")
    cur.execute("DROP INDEX orders_customer_id_ordered_at_idx")

    # --- E3: カバリング ---
    cur.execute("CREATE INDEX orders_customer_id_idx ON orders (customer_id)")
    plan = explain(cur, CUSTOMER_ORDERS.format(t="orders"))
    check("E3 customer_id 単一列: Bitmap Heap Scan ＋ Sort",
          "Bitmap Heap Scan" in node_types(plan) and "Sort" in node_types(plan), str(node_types(plan)))
    cur.execute("CREATE INDEX orders_customer_id_ordered_at_incl_idx ON orders (customer_id, ordered_at) "
                "INCLUDE (id, status)")
    plan = explain(cur, CUSTOMER_ORDERS.format(t="orders"))
    ios = find_nodes(plan, "Index Only Scan")
    check("E3 INCLUDE: Index Only Scan（逆順）で Sort なし、Heap Fetches 0",
          bool(ios) and ios[0].get("Heap Fetches") == 0 and "Sort" not in node_types(plan)
          and ios[0].get("Scan Direction") == "Backward", str(node_types(plan)))
    check("E3 INCLUDE 付きは customer_id 単一列の 5 倍以上の大きさ",
          size(cur, "orders_customer_id_ordered_at_incl_idx") > 5 * size(cur, "orders_customer_id_idx"))
    cur.execute("DROP INDEX orders_customer_id_idx, orders_customer_id_ordered_at_incl_idx")
    cur.execute("CREATE TABLE s09_orders WITH (autovacuum_enabled = false) AS SELECT * FROM orders")
    cur.execute("CREATE INDEX s09_orders_incl_idx ON s09_orders (customer_id, ordered_at) INCLUDE (id, status)")
    cur.execute("ANALYZE s09_orders")
    plan = explain(cur, CUSTOMER_ORDERS.format(t="s09_orders"))
    check("E3 Visibility Map が無いコピーでは Index Only Scan が選ばれない",
          "Index Only Scan" not in node_types(plan), str(node_types(plan)))
    cur.execute("VACUUM s09_orders")
    plan = explain(cur, CUSTOMER_ORDERS.format(t="s09_orders"))
    hf0 = [n.get("Heap Fetches") for n in find_nodes(plan, "Index Only Scan")]
    cur.execute("UPDATE s09_orders SET status = status WHERE customer_id = 12345")
    plan = explain(cur, CUSTOMER_ORDERS.format(t="s09_orders"))
    hf1 = [n.get("Heap Fetches") for n in find_nodes(plan, "Index Only Scan")]
    cur.execute("VACUUM (INDEX_CLEANUP ON) s09_orders")
    plan = explain(cur, CUSTOMER_ORDERS.format(t="s09_orders"))
    hf2 = [n.get("Heap Fetches") for n in find_nodes(plan, "Index Only Scan")]
    check("E3 VACUUM 後 0 → 20 行更新で Heap Fetches > 0 → 再 VACUUM で 0",
          hf0 == [0] and len(hf1) == 1 and hf1[0] > 0 and hf2 == [0], f"{hf0} {hf1} {hf2}")
    cur.execute("DROP TABLE s09_orders")

    # --- E4: 部分インデックス ---
    cur.execute("CREATE INDEX orders_ordered_at_idx ON orders (ordered_at)")
    cur.execute("CREATE INDEX orders_pending_ordered_at_idx ON orders (ordered_at) WHERE status = 'pending'")
    cur.execute("CREATE INDEX orders_cancelled_ordered_at_idx ON orders (ordered_at) WHERE status = 'cancelled'")
    full = size(cur, "orders_ordered_at_idx")
    check("E4 pending の部分インデックスは全行版の 2 割未満、cancelled は 6% 未満",
          size(cur, "orders_pending_ordered_at_idx") < 0.2 * full
          and size(cur, "orders_cancelled_ordered_at_idx") < 0.06 * full)
    plan = explain(cur, C_AFTER)
    scan = [n for n in walk(plan["Plan"]) if n.get("Index Name") == "orders_pending_ordered_at_idx"]
    check("E4 C（LIMIT 版）は部分インデックスを逆順に読み、Filter が無い",
          bool(scan) and "Filter" not in scan[0], str(index_names(plan)))
    plan = explain(cur, C_AFTER.replace("'pending'", "'completed'"), analyze=False)
    check("E4 completed は部分インデックスを使わない", "orders_pending_ordered_at_idx" not in index_names(plan)
          and "orders_cancelled_ordered_at_idx" not in index_names(plan))
    plan = explain(cur, "SELECT count(*) FROM orders WHERE status IN ('pending', 'cancelled') "
                        "AND ordered_at >= '2025-06-01' AND ordered_at < '2025-06-02'", analyze=False)
    check("E4 IN (pending, cancelled) は部分インデックスを使わない",
          index_names(plan) == {"orders_ordered_at_idx"}, str(index_names(plan)))
    cur.execute("PREPARE s09_q(text) AS SELECT id FROM orders WHERE status = $1 ORDER BY ordered_at DESC LIMIT 20")
    cur.execute("SET plan_cache_mode = force_generic_plan")
    cur.execute("EXPLAIN (FORMAT JSON) EXECUTE s09_q('pending')")
    generic = cur.fetchone()[0][0]
    cur.execute("SET plan_cache_mode = force_custom_plan")
    cur.execute("EXPLAIN (FORMAT JSON) EXECUTE s09_q('pending')")
    custom = cur.fetchone()[0][0]
    cur.execute("RESET plan_cache_mode")
    cur.execute("DEALLOCATE s09_q")
    check("E4 汎用プランでは部分インデックスを使わず、カスタムプランでは使う",
          "orders_pending_ordered_at_idx" not in index_names(generic)
          and "orders_pending_ordered_at_idx" in index_names(custom))
    cur.execute("DROP INDEX orders_ordered_at_idx, orders_pending_ordered_at_idx, orders_cancelled_ordered_at_idx")

    # --- E5: 式インデックス ---
    cur.execute("CREATE INDEX orders_customer_id_idx ON orders (customer_id)")
    cur.execute("CREATE INDEX customers_lower_email_idx ON customers (lower(email))")
    cur.execute("SELECT count(*) FROM pg_stats WHERE tablename = 'customers_lower_email_idx'")
    check("E5 作った直後は式の統計が無い", cur.fetchone()[0] == 0)
    plan = explain(cur, A_BEFORE)
    cust = nodes_on(plan, "customers")
    check("E5 ANALYZE 前：式インデックスは使うが、見積もりは既定値のまま Hash Join",
          "customers_lower_email_idx" in index_names(plan) and cust[0]["Plan Rows"] >= 100
          and "Hash Join" in node_types(plan), str(node_types(plan)))
    cur.execute("ANALYZE customers")
    cur.execute("SELECT count(*) FROM pg_stats WHERE tablename = 'customers_lower_email_idx'")
    check("E5 ANALYZE で式の統計ができる", cur.fetchone()[0] == 1)
    plan = explain(cur, A_BEFORE)
    check("E5 ANALYZE 後：Nested Loop で orders_customer_id_idx を引く",
          "Nested Loop" in node_types(plan) and "orders_customer_id_idx" in index_names(plan), str(node_types(plan)))
    try:
        cur.execute("CREATE INDEX orders_ordered_date_idx ON orders ((ordered_at::date))")
        ok = False
    except psycopg.errors.InvalidObjectDefinition as e:
        ok = "IMMUTABLE" in str(e)
    check("E5 (ordered_at::date) の式インデックスは IMMUTABLE でないため作れない", ok)
    cur.execute("CREATE INDEX orders_ordered_date_utc_idx ON orders (((ordered_at AT TIME ZONE 'UTC')::date))")
    cur.execute("ANALYZE orders")
    plan = explain(cur, "SELECT count(*) FROM orders WHERE (ordered_at AT TIME ZONE 'UTC')::date = DATE '2025-06-01'")
    check("E5 同じ式で書けば UTC の日付インデックスを使う", "orders_ordered_date_utc_idx" in index_names(plan))
    check("E5 その件数は 2,740", actual_total_rows(plan["Plan"]["Plans"][0]) == 2740)
    plan = explain(cur, "SELECT count(*) FROM orders WHERE ordered_at::date = DATE '2025-06-01'", analyze=False)
    check("E5 ordered_at::date と書くと使わない", "orders_ordered_date_utc_idx" not in index_names(plan))
    cur.execute("DROP INDEX orders_customer_id_idx, customers_lower_email_idx, orders_ordered_date_utc_idx")

    # --- E6: インデックスを増やすコスト（INSERT は交互に 5 回、UPDATE の HOT 件数） ---
    ddl = {
        "s09_w0": [],
        "s09_w2": ["CREATE UNIQUE INDEX {t}_id_idx ON {t} (id)", "CREATE INDEX {t}_cid_idx ON {t} (customer_id)"],
        "s09_w5": ["CREATE UNIQUE INDEX {t}_id_idx ON {t} (id)", "CREATE INDEX {t}_cid_idx ON {t} (customer_id)",
                   "CREATE INDEX {t}_oat_idx ON {t} (ordered_at)", "CREATE INDEX {t}_st_idx ON {t} (status)",
                   "CREATE INDEX {t}_cid_oat_idx ON {t} (customer_id, ordered_at)"],
    }
    for t, stmts in ddl.items():
        cur.execute(f"CREATE TABLE {t} (LIKE orders) WITH (fillfactor = 90, autovacuum_enabled = false)")
        for s in stmts:
            cur.execute(s.format(t=t))
    ins: dict[str, list[float]] = {t: [] for t in ddl}
    for _ in range(5):
        for t in ddl:
            cur.execute(f"TRUNCATE {t}")
            ins[t].append(exec_ms(cur, f"INSERT INTO {t} SELECT * FROM orders WHERE id <= 100000"))
    m = {t: statistics.median(v) for t, v in ins.items()}
    check("E6 INSERT 10 万行：5 本は 0 本の 3 倍以上遅い（中央値）", m["s09_w5"] > 3 * m["s09_w0"],
          " / ".join(f"{t} {v:.1f} ms" for t, v in m.items()))
    cur.execute("VACUUM (ANALYZE) s09_w0, s09_w2, s09_w5")
    cur.execute("SELECT pg_stat_reset_single_table_counters(oid) FROM pg_class "
                "WHERE relname IN ('s09_w0', 's09_w2', 's09_w5')")
    for t in ddl:
        cur.execute(FLIP.format(t=t))
    flush(cur)
    cur.execute("SELECT relname, n_tup_upd, n_tup_hot_upd FROM pg_stat_user_tables "
                "WHERE relname IN ('s09_w0', 's09_w2', 's09_w5') ORDER BY relname")
    hot = {r[0]: (r[1], r[2]) for r in cur.fetchall()}
    check("E6 status にインデックスが無い表（0 本・2 本）は 1 万行すべて HOT 更新",
          hot.get("s09_w0") == (10000, 10000) and hot.get("s09_w2") == (10000, 10000), str(hot))
    check("E6 status にインデックスがある表（5 本）は HOT 更新 0 件", hot.get("s09_w5") == (10000, 0), str(hot))
    cur.execute("VACUUM s09_w5")
    cur.execute("SELECT pg_stat_reset_single_table_counters('s09_w5'::regclass)")
    cur.execute("UPDATE s09_w5 SET status = status WHERE id % 10 = 1")
    flush(cur)
    cur.execute("SELECT n_tup_upd, n_tup_hot_upd FROM pg_stat_user_tables WHERE relname = 's09_w5'")
    check("E6 値の変わらない更新なら、インデックスのある列でも HOT", cur.fetchone() == (10000, 10000))
    cur.execute("DROP TABLE s09_w0, s09_w2, s09_w5")

    # --- E7: 使われていないインデックス ---
    for s in ("CREATE INDEX customers_email_idx ON customers (email)",
              "CREATE INDEX orders_customer_id_idx ON orders (customer_id)",
              "CREATE INDEX orders_ordered_at_idx ON orders (ordered_at)",
              "CREATE INDEX orders_status_idx ON orders (status)",
              "CREATE INDEX orders_status_ordered_at_idx ON orders (status, ordered_at)"):
        cur.execute(s)
    cur.execute(A_AFTER)
    cur.execute(C_AFTER)
    cur.execute(DAY_COUNT)
    cur.execute("SELECT status, count(*) FROM orders WHERE ordered_at >= '2025-06-01' AND ordered_at < '2025-06-08' "
                "GROUP BY status")
    flush(cur)
    cur.execute("SELECT indexrelname, idx_scan FROM pg_stat_user_indexes WHERE relname IN ('customers', 'orders') "
                "AND indexrelname NOT IN ('customers_pkey', 'orders_pkey')")
    scans = dict(cur.fetchall())
    check("E7 使われなかったのは orders_status_idx だけ",
          [k for k, v in scans.items() if v == 0] == ["orders_status_idx"], str(scans))
    check("E7 (status, ordered_at) は C の 1 回と、スキップスキャンの 7 回で idx_scan = 8",
          scans.get("orders_status_ordered_at_idx") == 8, str(scans.get("orders_status_ordered_at_idx")))
    before = idx_scan(cur, "orders_customer_id_idx")
    cur.execute("EXPLAIN (COSTS OFF) " + A_AFTER)
    flush(cur)
    check("E7 EXPLAIN（計画だけ）でも idx_scan が増える", idx_scan(cur, "orders_customer_id_idx") > before)
    cur.execute("DROP INDEX customers_email_idx, orders_customer_id_idx, orders_ordered_at_idx, orders_status_idx, "
                "orders_status_ordered_at_idx")

    # --- E8: BRIN / GIN / GiST ---
    cur.execute("SELECT attname, correlation FROM pg_stats WHERE tablename = 'orders' AND attname IN ('id', 'ordered_at')")
    corr = dict(cur.fetchall())
    check("E8 相関：id は 1、ordered_at はほぼ 0", corr["id"] > 0.99 and abs(corr["ordered_at"]) < 0.1, str(corr))
    cur.execute("CREATE INDEX orders_id_brin ON orders USING brin (id)")
    cur.execute("CREATE INDEX orders_ordered_at_brin ON orders USING brin (ordered_at)")
    check("E8 BRIN は 100 kB 未満", size(cur, "orders_id_brin") < 100_000)
    cur.execute("SET enable_indexscan = off")
    cur.execute("SET enable_indexonlyscan = off")
    plan = explain(cur, "SELECT count(*) FROM orders WHERE id BETWEEN 500000 AND 509999")
    heap = find_nodes(plan, "Bitmap Heap Scan")
    check("E8 id の BRIN：1 万行のために 128 ページだけ読む",
          "orders_id_brin" in index_names(plan) and bool(heap) and heap[0].get("Lossy Heap Blocks") == 128,
          str([n.get("Lossy Heap Blocks") for n in heap]))
    cur.execute("RESET enable_indexscan")
    cur.execute("RESET enable_indexonlyscan")
    plan = explain(cur, DAY_COUNT, analyze=False)
    check("E8 ordered_at の BRIN はプランナが選ばない", "orders_ordered_at_brin" not in index_names(plan))
    cur.execute("SET enable_seqscan = off")
    cur.execute("SET max_parallel_workers_per_gather = 0")
    plan = explain(cur, DAY_COUNT)
    heap = find_nodes(plan, "Bitmap Heap Scan")
    check("E8 強制すると ordered_at の BRIN は全 8,197 ページを候補にする",
          bool(heap) and heap[0].get("Lossy Heap Blocks") == 8197, str([n.get("Lossy Heap Blocks") for n in heap]))
    cur.execute("RESET enable_seqscan")
    cur.execute("RESET max_parallel_workers_per_gather")
    cur.execute("DROP INDEX orders_id_brin, orders_ordered_at_brin")

    cur.execute("CREATE TABLE s09_order_products AS SELECT oi.order_id, "
                "array_agg(oi.product_id ORDER BY oi.product_id) AS product_ids FROM order_items oi "
                "WHERE oi.order_id <= 200000 GROUP BY oi.order_id")
    cur.execute("VACUUM (ANALYZE) s09_order_products")
    gin_q = "SELECT count(*) FROM s09_order_products WHERE product_ids @> ARRAY[1234]"
    cur.execute(gin_q)
    seq_count = cur.fetchone()[0]
    seq_ms = [exec_ms(cur, gin_q) for _ in range(5)]
    cur.execute("CREATE INDEX s09_order_products_gin ON s09_order_products USING gin (product_ids)")
    plan = explain(cur, gin_q)
    check("E8 GIN：Bitmap Index Scan で 79 件", "s09_order_products_gin" in index_names(plan)
          and seq_count == 79 and actual_total_rows(plan["Plan"]["Plans"][0]) == 79)
    gin_ms = [exec_ms(cur, gin_q) for _ in range(5)]
    check("E8 GIN は全件読みより 10 倍以上速い（中央値）", statistics.median(seq_ms) > 10 * statistics.median(gin_ms),
          f"{statistics.median(seq_ms):.3f} ms → {statistics.median(gin_ms):.3f} ms")
    cur.execute("SELECT count(*) FROM s09_order_products WHERE product_ids @> ARRAY[1234, 1235]")
    check("E8 GIN：2 商品を両方含む注文は 39 件", cur.fetchone()[0] == 39)

    cur.execute("CREATE TABLE s09_deliveries AS SELECT id AS order_id, tstzrange(ordered_at + interval '1 day', "
                "ordered_at + interval '1 day' + ((1 + id % 4) || ' hours')::interval) AS delivery_window "
                "FROM orders WHERE id <= 200000")
    cur.execute("VACUUM (ANALYZE) s09_deliveries")
    cur.execute("CREATE INDEX s09_deliveries_window_gist ON s09_deliveries USING gist (delivery_window)")
    plan = explain(cur, "SELECT count(*) FROM s09_deliveries WHERE delivery_window @> timestamptz '2025-06-02 12:00+00'")
    check("E8 GiST：範囲の「含む」を索引で引き 54 件", "s09_deliveries_window_gist" in index_names(plan)
          and actual_total_rows(plan["Plan"]["Plans"][0]) == 54)
    cur.execute("CREATE TABLE s09_sale_periods (name text NOT NULL, period tstzrange NOT NULL, "
                "EXCLUDE USING gist (period WITH &&))")
    cur.execute("INSERT INTO s09_sale_periods VALUES ('夏のセール', tstzrange('2025-07-01', '2025-07-15'))")
    try:
        cur.execute("INSERT INTO s09_sale_periods VALUES ('お盆セール', tstzrange('2025-07-10', '2025-07-20'))")
        ok = False
    except psycopg.errors.ExclusionViolation:
        ok = True
    check("E8 GiST の排他制約で、重なる期間の 2 行目は入らない", ok)
    cur.execute("DROP TABLE s09_order_products, s09_deliveries, s09_sale_periods")

    # --- E9: Mid01 の 3 本を 1 つの設計で ---
    cur.execute("CREATE INDEX customers_email_idx ON customers (email)")
    cur.execute("CREATE INDEX orders_cand1_idx ON orders (customer_id, status, ordered_at)")
    a, c = explain(cur, A_AFTER), explain(cur, C_AFTER)
    check("E9 候補 1 (customer_id, status, ordered_at)：A は引けるが C は使えない",
          "orders_cand1_idx" in index_names(a) and "orders_cand1_idx" not in index_names(c))
    cur.execute("DROP INDEX orders_cand1_idx")
    cur.execute("CREATE INDEX orders_cand2_idx ON orders (status, customer_id, ordered_at)")
    a, c = explain(cur, A_AFTER), explain(cur, C_AFTER)
    a_scan = [n for n in walk(a["Plan"]) if n.get("Index Name") == "orders_cand2_idx"]
    check("E9 候補 2 (status, customer_id, ordered_at)：A はスキップスキャン（Index Searches: 7）",
          bool(a_scan) and a_scan[0].get("Index Searches") == 7, str([n.get("Index Searches") for n in a_scan]))
    check("E9 候補 2：C は並びに使えず Sort が要る", "Sort" in node_types(c), str(node_types(c)))
    cur.execute("DROP INDEX orders_cand2_idx")
    cur.execute("CREATE INDEX orders_cand3_idx ON orders (status, ordered_at)")
    a, c = explain(cur, A_AFTER), explain(cur, C_AFTER)
    check("E9 候補 3 (status, ordered_at)：C は満たすが A は orders を全件読む",
          "orders_cand3_idx" in index_names(c) and "Sort" not in node_types(c)
          and all(n["Node Type"] in ("Seq Scan", "Parallel Seq Scan") for n in nodes_on(a, "orders")))
    cur.execute("DROP INDEX orders_cand3_idx")
    cur.execute("CREATE INDEX orders_customer_id_idx ON orders (customer_id)")
    cur.execute("CREATE INDEX orders_ordered_at_idx ON orders (ordered_at)")
    cur.execute("CREATE INDEX orders_pending_ordered_at_idx ON orders (ordered_at) WHERE status = 'pending'")
    a, c, c0 = explain(cur, A_AFTER), explain(cur, C_AFTER), explain(cur, C_BEFORE)
    check("E9 採用した設計：A は Nested Loop ＋ orders_customer_id_idx",
          "Nested Loop" in node_types(a) and "orders_customer_id_idx" in index_names(a))
    check("E9 採用した設計：C は部分インデックス", "orders_pending_ordered_at_idx" in index_names(c)
          and "Sort" not in node_types(c))
    sorts = [n for n in find_nodes(c0, "Sort") if "ordered_at" in " ".join(n.get("Sort Key", []))]
    check("E9 書き換える前の C は、インデックスを足しても 136,646 行を並べる",
          bool(sorts) and actual_total_rows(sorts[0]["Plans"][0]) == 136646)
    conn.close()

    # --- MySQL ---
    my = mysql_connect()
    with my.cursor() as mc:
        mc.execute("EXPLAIN FORMAT=TREE SELECT id, customer_id FROM orders WHERE customer_id = 12345")
        check("MySQL: セカンダリインデックスは主キーを持つので id, customer_id は Covering index lookup",
              "covering index lookup" in mc.fetchone()[0].lower())
        mc.execute("EXPLAIN FORMAT=TREE SELECT id, ordered_at FROM orders WHERE customer_id = 12345")
        check("MySQL: ordered_at を足すと covering ではなくなる", "covering" not in mc.fetchone()[0].lower())
        mc.execute("CREATE INDEX customers_lower_email_idx ON customers ((lower(email)))")
        mc.execute("EXPLAIN FORMAT=TREE SELECT id FROM customers WHERE lower(email) = lower('User12345@Example.com')")
        check("MySQL: 関数インデックスで lower(email) を引く", "customers_lower_email_idx" in mc.fetchone()[0])
        mc.execute("CREATE INDEX orders_status_ordered_at_idx ON orders (status, ordered_at)")
        mc.execute("EXPLAIN FORMAT=TREE SELECT count(*) FROM orders "
                   "WHERE ordered_at >= '2025-06-01' AND ordered_at < '2025-06-02'")
        check("MySQL: 先頭列の無い count はスキップスキャン", "skip scan" in mc.fetchone()[0].lower())
        mc.execute("EXPLAIN FORMAT=TREE SELECT id, customer_id FROM orders "
                   "WHERE ordered_at >= '2025-06-01' AND ordered_at < '2025-06-02'")
        check("MySQL: インデックスに無い列を返すとスキップスキャンは使われない", "skip scan" not in mc.fetchone()[0].lower())
        mc.execute("DROP INDEX customers_lower_email_idx ON customers")
        mc.execute("DROP INDEX orders_status_ordered_at_idx ON orders")
    my.close()

    finish("S09 インデックス設計の実践")


if __name__ == "__main__":
    main()

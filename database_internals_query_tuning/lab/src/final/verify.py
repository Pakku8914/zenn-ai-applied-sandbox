"""Final 最終プロジェクト（遅いシステムの総合診断）— 自己検証。

出発点（tools/reset.sh 直後）から単独で実行する。章の SQL（sql/final/01・10・12）を psql でそのまま流し、
改善前 → 改善後を再現して、原因の分類（計画の形・見積もりの外れ・肥大化・ロック待ち）と改善の有無を判定する。
判定に使うのはノードの種類・実測の行数・クエリの結果・ページ数などの物理量・待ったかどうか・エラーの種類・
pg_stat_statements の呼び出し回数だけ（実行時間は使わない）。
4 テーブルの行は変えない（在庫と出荷待ちは final_ 接頭辞の作業用テーブル）。
"""

from __future__ import annotations

import subprocess
import sys
import threading
import time
from pathlib import Path

import psycopg
import pymysql
from psycopg import errors

from labcheck import actual_total_rows, check, explain, find_nodes, finish, mysql_connect, node_types, walk

sys.path.insert(0, str(Path(__file__).resolve().parent))
import workload  # noqa: E402  同じディレクトリの負荷スクリプト（5 本の SQL もここから使う）

SQL_DIR = Path(__file__).resolve().parents[2] / "sql" / "final"
TIMEOUTS = "-c statement_timeout=60s -c lock_timeout=20s"

Q1 = workload.Q1_CUSTOMER_ORDERS.replace("%s", "12345")
Q3 = workload.Q3_SHIP_QUEUE.replace("%s", "'東京'")
Q4 = workload.Q4_RANKING.replace("%s", "'文具'")
Q5 = workload.Q5_DAILY_SALES


def psql_file(name: str) -> None:
    """章の SQL ファイルを読者と同じく psql で流す（エラーで止める）。"""
    subprocess.run(["psql", "-X", "-q", "-v", "ON_ERROR_STOP=1", "-f", str(SQL_DIR / name)],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def conn() -> psycopg.Connection:
    # 自動プリペアを止める（止めないと SET や統計の変化が計画に効かなくなる）
    return psycopg.connect(autocommit=True, prepare_threshold=None, options=TIMEOUTS)


def one(cur, sql: str, params=None):
    cur.execute(sql, params)
    return cur.fetchone()[0]


def scans_on(plan: dict, relation: str) -> list[dict]:
    return [n for n in walk(plan["Plan"]) if n.get("Relation Name") == relation]


def index_names(plan: dict) -> set[str]:
    return {n["Index Name"] for n in walk(plan["Plan"]) if "Index Name" in n}


def sort_methods(plan: dict) -> list[str]:
    methods = []
    for n in find_nodes(plan, "Sort"):
        if "Sort Method" in n:
            methods.append(n["Sort Method"])
        methods += [w["Sort Method"] for w in n.get("Workers", []) if "Sort Method" in w]
    return methods


def stmt_calls(cur, prefix: str) -> list[int]:
    """pg_stat_statements のうち、本文が prefix で始まる行の calls（行ごと）。"""
    cur.execute("""SELECT calls FROM pg_stat_statements
                   WHERE dbid = (SELECT oid FROM pg_database WHERE datname = current_database()) AND toplevel
                     AND regexp_replace(query, '\\s+', ' ', 'g') LIKE %s
                   ORDER BY calls DESC""", (prefix + "%",))
    return [r[0] for r in cur.fetchall()]


class Background:
    """ブロックするかもしれない文を別スレッドで実行する。"""

    def __init__(self, c: psycopg.Connection, *sqls: str):
        self.error: Exception | None = None
        self.rows = None
        self.pid = c.info.backend_pid
        self.t = threading.Thread(target=self._run, args=(c, sqls), daemon=True)
        self.t.start()

    def _run(self, c, sqls):
        try:
            cur = c.cursor()
            for sql in sqls:
                cur.execute(sql)
            self.rows = cur.fetchall() if cur.description else cur.rowcount
        except Exception as e:  # noqa: BLE001 — エラーの種類を後で判定する
            self.error = e

    def join(self, timeout=25) -> bool:
        self.t.join(timeout)
        return not self.t.is_alive()


def wait_event(mon, pid: int, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        mon.execute("SELECT coalesce(wait_event_type, ''), coalesce(wait_event, '') FROM pg_stat_activity WHERE pid = %s",
                    (pid,))
        row = mon.fetchone()
        if row and row[0] == "Lock":
            return row
        time.sleep(0.05)
    return None


def verify_before(cur) -> dict:
    """改善前：01 で作ったシステムの症状と、原因の分類。"""
    results = {}
    # --- 出荷待ちキューの肥大化と古い統計（06） ---
    cur.execute("SELECT count(*) FROM final_ship_queue")
    live = cur.fetchone()[0]
    check("01: 出荷待ちは 5 日分の 13,100 行", live == 13100, str(live))
    cur.execute("SELECT pg_relation_size('final_ship_queue') / 8192, reltuples::bigint, reloptions::text "
                "FROM pg_class WHERE relname = 'final_ship_queue'")
    pages, reltuples, reloptions = cur.fetchone()
    check("06: テーブルは 7,000 ページ以上（生きている行は 100 ページ程度に収まる量）", pages >= 7000, str(pages))
    check("06: プランナが覚えている行数は一括投入のときのまま（956,522）", reltuples == 956522, str(reltuples))
    check("06: autovacuum がテーブル単位で止められている", reloptions == "{autovacuum_enabled=false}", str(reloptions))
    cur.execute("SELECT tuple_percent, free_percent FROM pgstattuple('final_ship_queue')")
    tuple_pct, free_pct = cur.fetchone()
    check("06: pgstattuple で生きている行は 5% 未満、空きが 90% 以上", tuple_pct < 5 and free_pct >= 90,
          f"tuple={tuple_pct}% free={free_pct}%")

    plan = explain(cur, Q3)
    scan = scans_on(plan, "final_ship_queue")
    check("Q3 改善前: final_ship_queue を全件走査する",
          [n["Node Type"] for n in scan] in (["Seq Scan"], ["Parallel Seq Scan"]), str([n["Node Type"] for n in scan]))
    check("Q3 改善前: 見積もり行数が実際の 10 倍以上に外れる（古い統計）",
          scan[0]["Plan Rows"] >= 10 * scan[0]["Actual Rows"], f"rows={scan[0]['Plan Rows']} actual={scan[0]['Actual Rows']}")
    cur.execute(Q3)
    results["q3"] = cur.fetchall()
    check("Q3: 東京の古い順 50 件", len(results["q3"]) == 50)

    # --- Q1：外部キー側のインデックス不足（03） ---
    cur.execute("""SELECT count(*) FROM pg_constraint c
                   WHERE c.contype = 'f' AND c.conrelid IN ('orders'::regclass, 'order_items'::regclass)
                     AND NOT EXISTS (SELECT 1 FROM pg_index i WHERE i.indrelid = c.conrelid AND i.indkey[0] = c.conkey[1])""")
    check("03: 外部キー 3 本のどれにもインデックスがない", cur.fetchone()[0] == 3)
    plan = explain(cur, Q1)
    items = scans_on(plan, "order_items")
    check("Q1 改善前: order_items を全件（200 万行）読む",
          len(items) == 1 and "Seq Scan" in items[0]["Node Type"] and round(actual_total_rows(items[0])) == 2_000_000,
          str([(n["Node Type"], actual_total_rows(n)) for n in items]))
    check("Q1 改善前: 結合は Hash Join", any("Hash Join" in t for t in node_types(plan)), str(node_types(plan)))
    cur.execute(Q1)
    results["q1"] = cur.fetchall()
    check("Q1: 顧客 12345 の直近 10 件", len(results["q1"]) == 10)

    # --- Q4：結合で明細を全件読む（07） ---
    plan = explain(cur, Q4)
    items = scans_on(plan, "order_items")
    check("Q4 改善前: Hash Join のために order_items を全件読む",
          len(items) == 1 and "Seq Scan" in items[0]["Node Type"] and round(actual_total_rows(items[0])) == 2_000_000
          and "Nested Loop" not in node_types(plan), str([(n["Node Type"], actual_total_rows(n)) for n in items]))
    cur.execute(Q4)
    results["q4"] = cur.fetchall()
    check("Q4: 上位 10 商品", len(results["q4"]) == 10)

    # --- Q5：ソートが work_mem に収まらない（08。判定は並列を止めて 1 本のソートにして行う） ---
    cur.execute("SET max_parallel_workers_per_gather = 0")
    plan = explain(cur, Q5)
    check("Q5 改善前: 47 万行のソートが外部ソートになる", "external merge" in sort_methods(plan), str(sort_methods(plan)))
    cur.execute("RESET max_parallel_workers_per_gather")
    cur.execute(Q5)
    results["q5"] = cur.fetchall()
    check("Q5: 90 日分", len(results["q5"]) == 90)
    return results


def verify_allocation_lock_long() -> None:
    """05：改善前の引き当て。行ロックを持ったまま決済 API を待つと、同じ商品の引き当てが待たされる。"""
    a, b, m = conn(), conn(), conn()
    ca, cb, cm = a.cursor(), b.cursor(), m.cursor()
    ca.execute("UPDATE final_products SET stock = 100000 WHERE id = 777")
    ca.execute("BEGIN")
    ca.execute("SELECT stock FROM final_products WHERE id = 777 FOR UPDATE")
    bg = Background(b, "BEGIN", "SET LOCAL lock_timeout = '3s'", "SELECT stock FROM final_products WHERE id = 777 FOR UPDATE")
    ev = wait_event(cm, bg.pid)
    check("05: 同じ商品の引き当ては待つ（wait_event = transactionid）", ev == ("Lock", "transactionid"), str(ev))
    check("05: 待たせている側は idle in transaction（決済 API の応答待ち）",
          one(cm, "SELECT state FROM pg_stat_activity WHERE pid = %s", (a.info.backend_pid,)) == "idle in transaction")
    check("05: pg_blocking_pids が待たせている側を指す",
          list(one(cm, "SELECT pg_blocking_pids(%s)", (bg.pid,))) == [a.info.backend_pid])
    bg.join()
    check("05: lock_timeout で B はエラーになる（55P03）", isinstance(bg.error, errors.LockNotAvailable), repr(bg.error))
    cb.execute("ROLLBACK")
    ca.execute("ROLLBACK")
    for c in (a, b, m):
        c.close()


def verify_allocation_lock_short() -> None:
    """14：改善後の引き当て。短いトランザクションなら待たず、在庫の判定も正しい（売り越さない）。"""
    a, b, m = conn(), conn(), conn()
    ca, cb, cm = a.cursor(), b.cursor(), m.cursor()
    ca.execute("UPDATE final_products SET stock = 100000 WHERE id = 777")
    before = one(cm, "SELECT count(*) FROM final_ship_queue")
    for c, customer in ((ca, 12345), (cb, 23456)):
        c.execute("SET lock_timeout = '1s'")
        c.execute("BEGIN")
        c.execute(workload.Q2_UPDATE_SHORT, (1, 777, 1))
        c.fetchone()
        c.execute(workload.Q2_ENQUEUE, (customer,))
        c.execute("COMMIT")
    check("14: 2 件の引き当てはどちらも待たずに終わる（在庫 100000 → 99998、出荷待ちに 2 行）",
          one(cm, "SELECT stock FROM final_products WHERE id = 777") == 99998
          and one(cm, "SELECT count(*) FROM final_ship_queue") == before + 2)

    ca.execute("UPDATE final_products SET stock = 1 WHERE id = 777")
    ca.execute("SET lock_timeout = '20s'")
    cb.execute("SET lock_timeout = '20s'")
    ca.execute("BEGIN")
    ca.execute(workload.Q2_UPDATE_SHORT, (1, 777, 1))
    got_a = ca.fetchall()
    bg = Background(b, "BEGIN", "UPDATE final_products SET stock = stock - 1 WHERE id = 777 AND stock >= 1 RETURNING stock")
    ev = wait_event(cm, bg.pid)
    check("14: 最後の 1 個を取り合うと、後の方は先の COMMIT を待つ", ev == ("Lock", "transactionid"), str(ev))
    ca.execute("COMMIT")
    bg.join()
    check("14: 先は 1 行、後は 0 行の更新（条件を評価し直して在庫切れになる）",
          got_a == [(0,)] and bg.error is None and bg.rows == [], f"a={got_a} b={bg.rows} err={bg.error!r}")
    cb.execute("ROLLBACK")
    check("14: 在庫は 0 で止まる（マイナスにならない）", one(cm, "SELECT stock FROM final_products WHERE id = 777") == 0)
    ca.execute("UPDATE final_products SET stock = 100000 WHERE id = 777")
    for c in (a, b, m):
        c.close()


def verify_workload_stats(cur, allocation: str) -> None:
    """workload.py の操作列が決定的で、pg_stat_statements に 1 本 1 行で記録されること。"""
    workload.run(ops=100, threads=2, allocation=allocation, api_ms=5, quiet=True)
    expected = {
        "SELECT o.id, o.ordered_at, o.status, count(*) AS items": 40,
        "SELECT order_id, customer_id, ordered_at FROM final_ship_queue": 20,
        "SELECT p.id, p.name, sum(oi.quantity) AS qty": 8,
        "SELECT date_trunc($1, o.ordered_at) AS day": 2,
    }
    for prefix, calls in expected.items():
        got = stmt_calls(cur, prefix)
        check(f"workload（{allocation}）: 「{prefix[:30]}…」が 1 行で {calls} 回", got == [calls], str(got))
    lock_calls = stmt_calls(cur, "SELECT stock FROM final_products WHERE id = $1 FOR UPDATE")
    short_calls = stmt_calls(cur, "UPDATE final_products SET stock = stock - $1 WHERE id = $2 AND stock >= $3")
    if allocation == "long":
        check("workload（long）: 引き当ての FOR UPDATE が 30 回", lock_calls == [30], str(lock_calls))
    else:
        check("workload（short）: FOR UPDATE は無く、条件付き UPDATE が 30 回", lock_calls == [] and short_calls == [30],
              f"for_update={lock_calls} update={short_calls}")


def verify_vacuum(cur) -> None:
    """12 の直後：autovacuum を戻して VACUUM (ANALYZE) した出荷待ちキュー。"""
    cur.execute("SELECT pg_relation_size('final_ship_queue') / 8192, reltuples::bigint, reloptions FROM pg_class "
                "WHERE relname = 'final_ship_queue'")
    pages, reltuples, reloptions = cur.fetchone()
    live = one(cur, "SELECT count(*) FROM final_ship_queue")
    check("12: autovacuum の設定を戻した（reloptions なし）", reloptions is None, str(reloptions))
    check("12: 統計が実際の行数に戻った（reltuples = 生きている行数）", reltuples == live, f"{reltuples} / {live}")
    check("12: VACUUM ではページ数は減らない（7,000 ページ以上のまま）", pages >= 7000, str(pages))
    check("12: 不要行は 0", one(cur, "SELECT n_dead_tup FROM pg_stat_user_tables WHERE relname = 'final_ship_queue'") == 0)
    cur.execute("SELECT tuple_percent, free_percent FROM pgstattuple('final_ship_queue')")
    tuple_pct, free_pct = cur.fetchone()
    check("12: VACUUM 後も生きている行は 5% 未満（空きが増えただけ）", tuple_pct < 5 and free_pct >= 90,
          f"tuple={tuple_pct}% free={free_pct}%")


def verify_after(cur, before: dict) -> None:
    cur.execute("""SELECT array_agg(indexrelname::text ORDER BY indexrelname) FROM pg_stat_user_indexes
                   WHERE relname IN ('orders', 'order_items', 'final_ship_queue')""")
    check("10: インデックスは主キー 3 本 ＋ 足した 3 本（orders_status_idx は消えた）",
          cur.fetchone()[0] == ["final_ship_queue_pkey", "final_ship_queue_region_ordered_at_idx",
                                "order_items_order_id_idx", "order_items_pkey", "orders_customer_id_idx", "orders_pkey"])

    # --- 5 本の計画の変化（13） ---
    plan = explain(cur, Q1)
    check("Q1 改善後: orders_customer_id_idx と order_items_order_id_idx を使う Nested Loop",
          {"orders_customer_id_idx", "order_items_order_id_idx"} <= index_names(plan) and "Nested Loop" in node_types(plan)
          and "Hash Join" not in node_types(plan), str(node_types(plan)))
    check("Q1 改善後: 明細は Index Only Scan（Heap Fetches 0）",
          any(n["Node Type"] == "Index Only Scan" and n["Heap Fetches"] == 0 for n in scans_on(plan, "order_items")))
    cur.execute(Q1)
    check("Q1: 改善前後で結果が同じ", cur.fetchall() == before["q1"])

    plan = explain(cur, Q3)
    check("Q3 改善後: (region, ordered_at) のインデックスを順に読み、Sort がない",
          index_names(plan) == {"final_ship_queue_region_ordered_at_idx"} and "Sort" not in node_types(plan),
          str(node_types(plan)))
    cur.execute(Q3)
    check("Q3: 改善前後で結果が同じ（古い順 50 件）", cur.fetchall() == before["q3"])

    plan = explain(cur, Q4)
    items = scans_on(plan, "order_items")
    check("Q4 改善後: 明細はカバリングの Index Only Scan（Nested Loop の内側）",
          [n["Node Type"] for n in items] == ["Index Only Scan"] and "Nested Loop" in node_types(plan),
          str([n["Node Type"] for n in items]))
    cur.execute(Q4)
    check("Q4: 改善前後で結果が同じ", cur.fetchall() == before["q4"])

    plan = explain(cur, Q5)
    items = scans_on(plan, "order_items")
    check("Q5 改善後: 計画は変わらない（order_items を全件読む Hash Join）",
          len(items) == 1 and "Seq Scan" in items[0]["Node Type"] and round(actual_total_rows(items[0])) == 2_000_000
          and any("Hash Join" in t for t in node_types(plan)), str(node_types(plan)))
    cur.execute(Q5)
    check("Q5: 改善前後で結果が同じ", cur.fetchall() == before["q5"])

    # --- ex02：カバリングにしなければ Q4 は Hash Join のまま ---
    cur.execute("BEGIN")
    cur.execute("CREATE INDEX order_items_order_id_plain_idx ON order_items (order_id)")
    cur.execute("DROP INDEX order_items_order_id_idx")
    plan = explain(cur, Q4)
    cur.execute("ROLLBACK")
    items = scans_on(plan, "order_items")
    check("ex02: INCLUDE なしのインデックスでは Q4 は Hash Join ＋ 明細の全件読みのまま",
          len(items) == 1 and "Seq Scan" in items[0]["Node Type"], str([n["Node Type"] for n in items]))

    # --- ex03：orders (ordered_at) を足すと Q4 はそれを使う（Q5 への影響は時間なので ex03 の実測を見る） ---
    cur.execute("BEGIN")
    cur.execute("CREATE INDEX orders_ordered_at_idx ON orders (ordered_at)")
    plan = explain(cur, Q4)
    cur.execute("ROLLBACK")
    check("ex03: orders (ordered_at) があれば Q4 は直近 7 日をインデックスで探す",
          "orders_ordered_at_idx" in index_names(plan), str(index_names(plan)))

    # --- ex04：work_mem を 64MB にすればソートはメモリに収まる（速くはならない。時間は ex04 の実測） ---
    cur.execute("SET work_mem = '64MB'")
    plan = explain(cur, Q5)
    cur.execute("RESET work_mem")
    check("ex04: work_mem = 64MB ではソートがすべてメモリ内（quicksort）", set(sort_methods(plan)) == {"quicksort"},
          str(sort_methods(plan)))

    # --- ex06：集計テーブル（マテリアライズドビュー）は Q5 と同じ結果 ---
    cur.execute("DROP MATERIALIZED VIEW IF EXISTS final_daily_sales")
    cur.execute("""CREATE MATERIALIZED VIEW final_daily_sales AS
                   SELECT date_trunc('day', o.ordered_at) AS day, count(DISTINCT o.customer_id) AS buyers,
                          sum(oi.quantity * oi.unit_price) AS sales
                   FROM orders o JOIN order_items oi ON oi.order_id = o.id
                   WHERE o.status <> 'cancelled' GROUP BY 1""")
    cur.execute("SELECT day, buyers, sales FROM final_daily_sales "
                "WHERE day >= '2025-10-03' AND day < '2026-01-01' ORDER BY day")
    check("ex06: マテリアライズドビューの 90 日分は Q5 と一致する", cur.fetchall() == before["q5"])
    cur.execute("DROP MATERIALIZED VIEW final_daily_sales")

    # --- ex07：VACUUM FULL で出荷待ちキューが縮む ---
    pages = one(cur, "SELECT pg_relation_size('final_ship_queue') / 8192")
    live = one(cur, "SELECT count(*) FROM final_ship_queue")
    cur.execute("SET lock_timeout = '2s'")
    cur.execute("VACUUM FULL final_ship_queue")
    cur.execute("RESET lock_timeout")
    pages_after = one(cur, "SELECT pg_relation_size('final_ship_queue') / 8192")
    check("ex07: VACUUM FULL で 7,000 ページ以上 → 200 ページ未満", pages_after < 200, f"{pages} → {pages_after}")
    check("ex07: 生きている行は変わらない", one(cur, "SELECT count(*) FROM final_ship_queue") == live)


def verify_same_query_two_rows(cur) -> None:
    """ex01：パラメータの型が違うと、同じ SELECT が pg_stat_statements の別の行になる。"""
    cur.execute("PREPARE final_ex01_a(integer) AS SELECT count(*) FROM orders WHERE customer_id = $1")
    cur.execute("PREPARE final_ex01_b(integer) AS SELECT count(*) FROM orders WHERE customer_id = $1")
    cur.execute("PREPARE final_ex01_c(smallint) AS SELECT count(*) FROM orders WHERE customer_id = $1")
    for name, value in (("a", 40000), ("b", 45000), ("c", 12345)):
        cur.execute(f"EXECUTE final_ex01_{name}({value})")
    cur.execute("""SELECT count(DISTINCT queryid) FROM pg_stat_statements
                   WHERE dbid = (SELECT oid FROM pg_database WHERE datname = current_database())
                     AND query LIKE 'PREPARE final_ex01%'""")
    check("ex01: 型が同じ a・b は 1 行、型が違う c は別の行（queryid が 2 種類）", cur.fetchone()[0] == 2)
    cur.execute("DEALLOCATE ALL")


def verify_mysql() -> None:
    a, b = mysql_connect(), mysql_connect()
    with a.cursor() as ca, b.cursor() as cb:
        ca.execute(Q1.replace("\n", " "))
        check("MySQL: Q1 は同じ 10 行を返す", len(ca.fetchall()) == 10)
        ca.execute("EXPLAIN ANALYZE " + Q1)
        tree = ca.fetchone()[0]
        check("MySQL: 外部キー用のインデックス（fk_orders_customer・fk_items_order）で Nested loop",
              "fk_orders_customer" in tree and "fk_items_order" in tree and "Nested loop" in tree, tree.splitlines()[0])
        ca.execute("DROP TABLE IF EXISTS final_products")
        ca.execute("CREATE TABLE final_products (PRIMARY KEY (id)) AS "
                   "SELECT id, name, category, price, 100000 AS stock FROM products")
        ca.execute("BEGIN")
        ca.execute("SELECT stock FROM final_products WHERE id = 777 FOR UPDATE")
        cb.execute("SET SESSION innodb_lock_wait_timeout = 1")
        cb.execute("BEGIN")
        codes = []
        for sql in ("SELECT stock FROM final_products WHERE id = 777 FOR UPDATE",
                    "SELECT stock FROM final_products WHERE id = 777 FOR UPDATE NOWAIT"):
            try:
                cb.execute(sql)
                codes.append(0)
            except pymysql.err.OperationalError as e:
                codes.append(e.args[0])
        check("MySQL: 待つと innodb_lock_wait_timeout で 1205、NOWAIT はすぐ 3572", codes == [1205, 3572], str(codes))
        cb.execute("SELECT stock FROM final_products WHERE id = 777 FOR UPDATE SKIP LOCKED")
        check("MySQL: SKIP LOCKED はロック中の行を飛ばす（0 行）", cb.fetchall() == ())
        cb.execute("ROLLBACK")
        ca.execute("ROLLBACK")
        cb.execute("UPDATE final_products SET stock = stock - 1 WHERE id = 777 AND stock >= 1")
        check("MySQL: 条件付き UPDATE の 1 文で引き当てられる", cb.rowcount == 1)
        ca.execute("DROP TABLE final_products")
    a.close()
    b.close()


def main() -> None:
    psql_file("01_setup.sql")
    c = conn()
    cur = c.cursor()

    before = verify_before(cur)
    verify_workload_stats(cur, "long")
    cur.execute("SELECT idx_scan FROM pg_stat_user_indexes WHERE indexrelname = 'orders_status_idx'")
    check("09: もともとある orders_status_idx は workload の後も idx_scan = 0", cur.fetchone()[0] == 0)
    verify_allocation_lock_long()
    verify_same_query_two_rows(cur)

    cur.execute("SELECT pg_indexes_size('orders') + pg_indexes_size('order_items') + pg_indexes_size('final_ship_queue')")
    size_before = cur.fetchone()[0]
    psql_file("10_index_set.sql")
    psql_file("12_vacuum_strategy.sql")
    verify_vacuum(cur)
    cur.execute("SELECT pg_indexes_size('orders') + pg_indexes_size('order_items') + pg_indexes_size('final_ship_queue')")
    size_after = cur.fetchone()[0]
    check("10: インデックスの合計サイズは増える（カバリングの分が大きい）", size_after > size_before * 1.5,
          f"{size_before // 2**20} MB → {size_after // 2**20} MB")

    verify_allocation_lock_short()
    verify_workload_stats(cur, "short")
    verify_after(cur, before)
    c.close()

    verify_mysql()
    finish("Final 遅いシステムの総合診断")


if __name__ == "__main__":
    main()

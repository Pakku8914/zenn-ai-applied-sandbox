"""S14 バッファ管理とキャッシュ — 自己検証。

出発点（tools/reset.sh 直後）から単独で実行する。作業用テーブル s14_*（新しい表）と、章で作るインデックスだけを変更する。
判定に使うのは、Buffers の hit / read / dirtied / written のページ数（共有バッファから追い出した直後・読み込んだ直後など、
状態を自分で決めてから測るので決定的）、共有バッファに載っているページ数（pg_buffercache）、pg_statio_* の累計、
計画のノードの種類（random_page_cost / effective_cache_size を変えたとき）、設定の context。
時間は random_page_cost を下げた「1 週間分の文具の売上」（実測で約 3.3 倍）にだけ「速くなる」の緩い条件で使う。
pg_buffercache_evict_relation・pg_stat_reset・pg_stat_reset_shared('io')・CHECKPOINT を使う（サーバーを独り占めしている前提）。
"""

from __future__ import annotations

import statistics
import time

from psycopg import errors

from labcheck import check, explain, finish, find_nodes, mysql_connect, node_types, pg_connect


def one(cur, sql: str, params=None):
    cur.execute(sql, params)
    return cur.fetchone()[0]


def bufs(res: dict) -> tuple[int, int, int, int]:
    p = res["Plan"]
    return (p.get("Shared Hit Blocks", 0), p.get("Shared Read Blocks", 0),
            p.get("Shared Dirtied Blocks", 0), p.get("Shared Written Blocks", 0))


def cached_pages(cur, rel: str) -> int:
    return one(cur, """SELECT count(*) FROM pg_buffercache WHERE relfilenode = pg_relation_filenode(%s::regclass)
                       AND reldatabase = (SELECT oid FROM pg_database WHERE datname = current_database())""", (rel,))


def evict(cur, rel: str) -> int:
    return one(cur, "SELECT buffers_evicted FROM pg_buffercache_evict_relation(%s::regclass)", (rel,))


def fresh(cur, name: str, like: str = "orders") -> None:
    cur.execute("SET client_min_messages = warning")
    cur.execute(f"DROP TABLE IF EXISTS {name}")
    cur.execute("RESET client_min_messages")
    cur.execute(f"CREATE TABLE {name} (LIKE {like}) WITH (autovacuum_enabled = off)")


def verify_buffercache(cur) -> None:
    cur.execute("CREATE EXTENSION IF NOT EXISTS pg_buffercache")
    cur.execute("CREATE EXTENSION IF NOT EXISTS pg_prewarm")
    # sql/session14/02 と同じく並列なし（並列だとワーカーごとにリングバッファを持つ）
    cur.execute("SET max_parallel_workers_per_gather = 0")
    total = one(cur, "SELECT buffers_used + buffers_unused FROM pg_buffercache_summary()")
    check("shared_buffers = 256MB ＝ 8KB の枠が 32768 個", one(cur, "SHOW shared_buffers") == "256MB" and total == 32768, str(total))

    evict(cur, "customers")
    r1 = bufs(explain(cur, "SELECT count(*) FROM customers", buffers=True))
    r2 = bufs(explain(cur, "SELECT count(*) FROM customers", buffers=True))
    check("customers（516 ページ）: 追い出した直後は read 516、2 回目は hit 516",
          r1[:2] == (0, 516) and r2[:2] == (516, 0), f"1回目={r1} 2回目={r2}")

    evict(cur, "orders")
    o1 = bufs(explain(cur, "SELECT count(*) FROM orders", buffers=True))
    o2 = bufs(explain(cur, "SELECT count(*) FROM orders", buffers=True))
    left = cached_pages(cur, "orders")
    check("orders（8197 ページ ＞ 共有バッファの 1/4）: 追い出した直後は read 8197", o1[:2] == (0, 8197), str(o1))
    check("2 回目もほとんど read（Seq Scan はリングバッファを使い回すので、共有バッファに残るのは一部だけ）",
          o2[1] > 7000 and left < 1000, f"2回目={o2} 残ったページ={left}")

    evict(cur, "orders")
    loaded = one(cur, "SELECT pg_prewarm('orders')")
    o3 = bufs(explain(cur, "SELECT count(*) FROM orders", buffers=True))
    check("pg_prewarm('orders') で 8197 ページを読み込むと、次の Seq Scan は 1 回目からすべて hit",
          loaded == 8197 and cached_pages(cur, "orders") == 8197 and o3[:2] == (8197, 0), f"prewarm={loaded} {o3}")

    # 1 日分（ランダムに 2,740 ページ）は、共有バッファに無いと 1 回目が遅い（OS のキャッシュから 1 ページずつ読む）
    cur.execute("CREATE INDEX orders_ordered_at_idx ON orders (ordered_at)")
    day = "SELECT * FROM orders WHERE ordered_at >= '2025-06-01' AND ordered_at < '2025-06-02'"
    cold, hot = [], []
    for _ in range(5):
        evict(cur, "orders")
        evict(cur, "orders_ordered_at_idx")
        rc = explain(cur, day, buffers=True)
        rh = explain(cur, day, buffers=True)
        cold.append(rc["Execution Time"])
        hot.append(rh["Execution Time"])
    check("1 日分: 追い出した直後は read 2750（ヒープ 2740 ＋ インデックス 10）、2 回目は hit 2750",
          bufs(rc)[:2] == (0, 2750) and bufs(rh)[:2] == (2750, 0), f"{bufs(rc)} {bufs(rh)}")
    check("1 日分: 追い出した直後の 1 回目は 2 回目より遅い（5 回の中央値。実測で約 10 倍）",
          statistics.median(cold) > 2 * statistics.median(hot),
          f"cold={statistics.median(cold):.2f}ms hot={statistics.median(hot):.2f}ms")
    cur.execute("DROP INDEX orders_ordered_at_idx")
    cur.execute("RESET max_parallel_workers_per_gather")


def flush_stats(cur) -> None:
    """この接続のまだ反映していない統計を反映させる（反映は次に待機状態になったとき）。"""
    cur.execute("SELECT pg_stat_force_next_flush()")
    time.sleep(0.2)
    cur.execute("SELECT 1")


def verify_hit_ratio(cur) -> None:
    cur.execute("SET max_parallel_workers_per_gather = 0")
    # 前の処理の未反映の統計がリセットの後に足されないよう、先に反映させてから 0 に戻す
    flush_stats(cur)
    cur.execute("SELECT pg_stat_reset()")
    for rel in ("orders", "orders_pkey", "customers"):
        evict(cur, rel)
    for _ in range(3):
        cur.execute("SELECT count(*) FROM orders")
    for _ in range(3):
        cur.execute("SELECT sum(length(name)) FROM customers WHERE id BETWEEN 1 AND 1000")
    flush_stats(cur)
    cur.execute("""SELECT relname, heap_blks_read, heap_blks_hit FROM pg_statio_user_tables
                   WHERE relname IN ('orders', 'customers') ORDER BY relname""")
    st = {r[0]: r[1:] for r in cur.fetchall()}
    o_read, o_hit = st["orders"]
    c_read, c_hit = st["customers"]
    check("orders を 3 回 Seq Scan: heap_blks_read が 2 万ページ超・ヒット率 10% 未満（リングバッファのため）",
          o_read > 20000 and o_hit / (o_hit + o_read) < 0.10, f"read={o_read} hit={o_hit}")
    check("customers の同じ範囲を 3 回: 1 回目に読んだ十数ページだけが read、2・3 回目は同じページが hit（ヒット率 2/3）",
          0 < c_read < 20 and c_hit == 2 * c_read, f"read={c_read} hit={c_hit}")
    cur.execute("RESET max_parallel_workers_per_gather")


def verify_dirtied_written(cur) -> None:
    cur.execute("SET max_parallel_workers_per_gather = 0")
    fresh(cur, "s14_t")
    cur.execute("INSERT INTO s14_t SELECT * FROM orders WHERE id <= 100000 ORDER BY id")
    cur.execute("CHECKPOINT")
    d1 = bufs(explain(cur, "SELECT count(*) FROM s14_t", buffers=True))
    d2 = bufs(explain(cur, "SELECT count(*) FROM s14_t", buffers=True))
    check("チェックポイント後の 1 回目の SELECT: 全 820 ページで dirtied（ヒントビット）。2 回目は 0",
          d1[2] == 820 and d2[2] == 0, f"1回目={d1} 2回目={d2}")
    cur.execute("UPDATE s14_t SET status = status WHERE id <= 10000")
    cur.execute("CHECKPOINT")
    d3 = bufs(explain(cur, "SELECT count(*) FROM s14_t", buffers=True))
    check("UPDATE → チェックポイント → SELECT: 古い版と新しい版のページ（約 160）が dirtied", 100 < d3[2] < 300, str(d3))

    flush_stats(cur)
    cur.execute("SELECT pg_stat_reset_shared('io')")
    fresh(cur, "s14_big", "order_items")
    fresh(cur, "s14_big2", "order_items")
    w1 = bufs(explain(cur, "INSERT INTO s14_big SELECT * FROM order_items", buffers=True))
    explain(cur, "INSERT INTO s14_big2 SELECT * FROM order_items", buffers=True)
    check("200 万行の INSERT: dirtied 14706、written はファイルの拡張分（14706 ページ以上）も数える",
          w1[2] == 14706 and w1[3] >= 14706, str(w1))
    dirty = one(cur, "SELECT buffers_dirty FROM pg_buffercache_summary()")
    cur.execute("SET enable_seqscan = off")
    cur.execute("SET enable_bitmapscan = off")
    w2 = bufs(explain(cur, "SELECT sum(quantity) FROM order_items WHERE id <= 1000000", buffers=True))
    cur.execute("RESET enable_seqscan")
    cur.execute("RESET enable_bitmapscan")
    check("共有バッファがダーティなページで埋まっていると、SELECT でも空き枠を作るために自分で書き出す（written > 0）",
          dirty > 20000 and w2[3] > 0, f"dirty={dirty} select={w2}")
    cur.execute("CHECKPOINT")
    flush_stats(cur)
    cur.execute("""SELECT backend_type, sum(writes) FROM pg_stat_io WHERE object = 'relation'
                   AND backend_type IN ('client backend', 'checkpointer') GROUP BY backend_type""")
    w = dict(cur.fetchall())
    check("pg_stat_io: SQL を実行した接続（client backend）もチェックポインタもデータファイルへ書いている",
          (w.get("client backend") or 0) > 0 and (w.get("checkpointer") or 0) > 0, str(w))
    cur.execute("RESET max_parallel_workers_per_gather")


JOIN = """SELECT sum(oi.quantity * oi.unit_price) AS sales, count(*) AS lines
FROM orders o JOIN order_items oi ON oi.order_id = o.id JOIN products p ON p.id = oi.product_id
WHERE o.ordered_at >= '2025-03-01' AND o.ordered_at < '2025-03-08' AND o.status <> 'cancelled' AND p.category = '文具'"""


def verify_cost_params(cur) -> None:
    cur.execute("SET max_parallel_workers_per_gather = 0")
    cur.execute("CREATE INDEX order_items_order_id_idx ON order_items (order_id)")
    times = {"default": [], "rpc": []}
    for _ in range(3):
        cur.execute("RESET random_page_cost")
        r0 = explain(cur, JOIN)
        times["default"].append(r0["Execution Time"])
        cur.execute("SET random_page_cost = 1.1")
        r1 = explain(cur, JOIN)
        times["rpc"].append(r1["Execution Time"])
    cur.execute("RESET random_page_cost")
    check("1 週間分の文具の売上（既定）: Hash Join だけで Nested Loop なし", "Nested Loop" not in node_types(r0)
          and node_types(r0).count("Hash Join") == 2, str(node_types(r0)))
    inner = [n for n in find_nodes(r1, "Index Scan") if n.get("Index Name") == "order_items_order_id_idx"]
    check("random_page_cost = 1.1: プランナ自身が Nested Loop ＋ order_items_order_id_idx の Index Scan を選ぶ",
          "Nested Loop" in node_types(r1) and len(inner) == 1, str(node_types(r1)))
    check("random_page_cost = 1.1 の計画の方が速い（3 回の中央値。実測で約 3.3 倍）",
          statistics.median(times["rpc"]) < statistics.median(times["default"]),
          f"default={statistics.median(times['default']):.1f}ms rpc1.1={statistics.median(times['rpc']):.1f}ms")

    cur.execute("CREATE INDEX orders_ordered_at_idx ON orders (ordered_at)")
    allq = "SELECT * FROM orders ORDER BY ordered_at"
    t0 = node_types(explain(cur, allq, analyze=False))
    cur.execute("SET random_page_cost = 1.1")
    t1 = node_types(explain(cur, allq, analyze=False))
    cur.execute("RESET random_page_cost")
    cur.execute("SET effective_cache_size = '64MB'")
    t2 = node_types(explain(cur, allq, analyze=False))
    cur.execute("RESET effective_cache_size")
    check("全件を ordered_at 順に: 既定も random_page_cost = 1.1 も Index Scan のまま", t0 == t1 == ["Index Scan"], f"{t0} {t1}")
    check("effective_cache_size = 64MB（テーブルより小さい）にすると Seq Scan ＋ Sort に変わる", t2 == ["Sort", "Seq Scan"], str(t2))

    cur.execute("DROP INDEX orders_ordered_at_idx")
    cur.execute("CREATE INDEX orders_customer_id_ordered_at_idx ON orders (customer_id, ordered_at)")
    cnt = "SELECT count(*) FROM orders WHERE ordered_at >= '2025-06-01' AND ordered_at < '2025-06-02'"
    s0 = node_types(explain(cur, cnt, analyze=False))
    cur.execute("SET random_page_cost = 1.1")
    s1 = node_types(explain(cur, cnt, analyze=False))
    cur.execute("RESET random_page_cost")
    check("(customer_id, ordered_at) と ordered_at だけの条件: 既定は Seq Scan、1.1 では Index Only Scan",
          "Seq Scan" in s0 and "Index Only Scan" in s1, f"{s0} {s1}")
    cur.execute("DROP INDEX orders_customer_id_ordered_at_idx")
    cur.execute("RESET max_parallel_workers_per_gather")


def verify_memory_settings(cur) -> None:
    cur.execute("""SELECT name, context FROM pg_settings WHERE name IN
                   ('shared_buffers', 'work_mem', 'maintenance_work_mem', 'effective_cache_size')""")
    ctx = dict(cur.fetchall())
    check("shared_buffers だけが再起動の必要な設定（postmaster）、ほかはセッションで変えられる（user）",
          ctx == {"shared_buffers": "postmaster", "work_mem": "user", "maintenance_work_mem": "user",
                  "effective_cache_size": "user"}, str(ctx))
    try:
        cur.execute("SET shared_buffers = '512MB'")
        refused = False
    except errors.CantChangeRuntimeParam:
        refused = True
    check("SET shared_buffers はエラー（55P02）", refused)
    cur.execute("SET effective_cache_size = '1TB'")
    check("effective_cache_size は実メモリより大きな値でもすぐ設定できる（メモリを確保しない）",
          one(cur, "SHOW effective_cache_size") == "1TB")
    cur.execute("RESET effective_cache_size")


def verify_mysql() -> None:
    m = mysql_connect()
    cur = m.cursor()
    cur.execute("SHOW VARIABLES WHERE Variable_name IN ('innodb_buffer_pool_size', 'innodb_flush_method')")
    v = dict(cur.fetchall())
    check("MySQL: バッファプール 256MB・O_DIRECT（OS のキャッシュを通さない）",
          v.get("innodb_buffer_pool_size") == "268435456" and v.get("innodb_flush_method") == "O_DIRECT", str(v))

    def reads() -> tuple[int, int]:
        cur.execute("""SELECT VARIABLE_NAME, VARIABLE_VALUE FROM performance_schema.global_status
                       WHERE VARIABLE_NAME IN ('Innodb_buffer_pool_read_requests', 'Innodb_buffer_pool_reads')""")
        d = {k: int(x) for k, x in cur.fetchall()}
        return d["Innodb_buffer_pool_read_requests"], d["Innodb_buffer_pool_reads"]

    cur.execute("SELECT SUM(LENGTH(status)) FROM orders")
    cur.fetchall()
    a = reads()
    cur.execute("SELECT SUM(LENGTH(status)) FROM orders")
    cur.fetchall()
    b = reads()
    check("MySQL: 2 回目の全件読みは論理読み取りだけでディスクからの読み取りがほぼ 0",
          b[0] - a[0] > 1000 and b[1] - a[1] <= 10, f"read_requests+{b[0] - a[0]} reads+{b[1] - a[1]}")
    cur.execute("""SELECT INDEX_NAME, COUNT(*) FROM information_schema.INNODB_BUFFER_PAGE
                   WHERE TABLE_NAME = CONCAT('`', DATABASE(), '`.`orders`') GROUP BY INDEX_NAME""")
    pages = dict(cur.fetchall())
    check("MySQL: INNODB_BUFFER_PAGE で orders のクラスタ化インデックス（PRIMARY）のページがバッファプールに見える",
          pages.get("PRIMARY", 0) > 1000, str(pages))
    m.close()


def main() -> None:
    c = pg_connect()
    c.prepare_threshold = None
    cur = c.cursor()
    verify_buffercache(cur)
    verify_hit_ratio(cur)
    verify_dirtied_written(cur)
    verify_cost_params(cur)
    verify_memory_settings(cur)
    c.close()
    verify_mysql()
    finish("S14 バッファ管理とキャッシュ")


if __name__ == "__main__":
    main()

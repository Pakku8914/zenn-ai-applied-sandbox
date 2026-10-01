"""横断復習③（S09〜S12）— 自己検証。

出発点（tools/reset.sh 直後）から単独で実行する。作業用テーブル r03_*（r03_orders は 100万行のコピー）だけを変更する。
判定に使うのは、ロックの種類・待ったかどうか・relfilenode（書き換えたか）・HOT 更新の数・計画のノードの種類・
実測の行数・見積もりと実測の「桁」の比（見積もりの正確な値は使わない）・idx_scan・xmax に入った番号だけ。時間は使わない。
最後に「操作 × 同時に流れる SELECT / UPDATE が待つか」の表を表示する。
"""

from __future__ import annotations

import threading
import time

import psycopg
from psycopg import errors

from labcheck import actual_total_rows, check, explain, find_nodes, finish, mysql_connect, node_types

TIMEOUTS = "-c statement_timeout=120s -c lock_timeout=60s"


def conn() -> psycopg.Connection:
    return psycopg.connect(autocommit=True, options=TIMEOUTS, prepare_threshold=None)


def one(cur, sql: str, params=None):
    cur.execute(sql, params)
    return cur.fetchone()[0]


def setup_orders(cur) -> None:
    cur.execute("SET client_min_messages = warning")
    cur.execute("DROP TABLE IF EXISTS r03_orders, r03_customers")
    cur.execute("RESET client_min_messages")
    cur.execute("CREATE TABLE r03_orders (LIKE orders) WITH (autovacuum_enabled = off)")
    cur.execute("INSERT INTO r03_orders SELECT * FROM orders ORDER BY id")
    cur.execute("SELECT pg_stat_force_next_flush()")
    time.sleep(0.5)
    cur.execute("ALTER TABLE r03_orders ADD PRIMARY KEY (id)")
    cur.execute("VACUUM (ANALYZE) r03_orders")


def my_locks(cur) -> set:
    cur.execute("SELECT relation::regclass::text, mode FROM pg_locks WHERE pid = pg_backend_pid() AND locktype = 'relation' "
                "AND (relation::regclass::text LIKE 'r03%%' OR relation = 'customers'::regclass)")
    return set(cur.fetchall())


OPS = {
    "CREATE INDEX": "CREATE INDEX r03_orders_customer_idx ON r03_orders (customer_id)",
    "ANALYZE": "ANALYZE r03_orders",
    "CREATE STATISTICS": "CREATE STATISTICS r03_orders_stats (dependencies) ON customer_id, ordered_at FROM r03_orders",
    "ADD COLUMN": "ALTER TABLE r03_orders ADD COLUMN note text",
    "ALTER COLUMN TYPE": "ALTER TABLE r03_orders ALTER COLUMN customer_id TYPE bigint",
    "ADD FOREIGN KEY": "ALTER TABLE r03_orders ADD CONSTRAINT r03_orders_customer_fk FOREIGN KEY (customer_id) REFERENCES customers (id)",
    "REINDEX": "REINDEX INDEX r03_orders_pkey",
    "TRUNCATE": "TRUNCATE r03_orders",
}
EXPECTED_LOCKS = {
    "CREATE INDEX": {("r03_orders", "ShareLock"), ("r03_orders_customer_idx", "AccessExclusiveLock")},
    "ANALYZE": {("r03_orders", "ShareUpdateExclusiveLock"), ("r03_orders_pkey", "AccessShareLock")},
    "CREATE STATISTICS": {("r03_orders", "ShareUpdateExclusiveLock")},
    "ADD COLUMN": {("r03_orders", "AccessExclusiveLock")},
    "ALTER COLUMN TYPE": {("r03_orders", "AccessExclusiveLock"), ("r03_orders", "ShareLock"), ("r03_orders_pkey", "AccessExclusiveLock")},
    "ADD FOREIGN KEY": {("r03_orders", "ShareRowExclusiveLock"), ("customers", "ShareRowExclusiveLock"),
                        ("r03_orders", "AccessShareLock"), ("customers", "AccessShareLock"), ("customers", "RowShareLock"),
                        ("r03_orders_pkey", "AccessShareLock")},
    "REINDEX": {("r03_orders", "ShareLock"), ("r03_orders_pkey", "AccessExclusiveLock")},
    "TRUNCATE": {("r03_orders", "AccessExclusiveLock"), ("r03_orders", "ShareLock"), ("r03_orders_pkey", "AccessExclusiveLock")},
}
# 同時に流れる SELECT（主キーで 1 行）/ UPDATE（別の 1 行）が待つか（PostgreSQL のロックの競合表どおり）
EXPECTED_BLOCK = {
    "CREATE INDEX": (False, True), "ANALYZE": (False, False), "CREATE STATISTICS": (False, False),
    "ADD COLUMN": (True, True), "ALTER COLUMN TYPE": (True, True), "ADD FOREIGN KEY": (False, True),
    "REINDEX": (True, True), "TRUNCATE": (True, True),
}


def blocks(c: psycopg.Connection, sql: str) -> bool:
    cur = c.cursor()
    cur.execute("BEGIN")
    cur.execute("SET LOCAL lock_timeout = '1s'")
    try:
        cur.execute(sql)
        cur.execute("ROLLBACK")
        return False
    except errors.LockNotAvailable:
        cur.execute("ROLLBACK")
        return True


def verify_lock_modes() -> dict:
    a, b = conn(), conn()
    ca = a.cursor()
    setup_orders(ca)
    matrix = {}
    for name, sql in OPS.items():
        ca.execute("BEGIN")
        ca.execute(sql)
        locks = my_locks(ca)
        sel = blocks(b, "SELECT status FROM r03_orders WHERE id = 1")
        upd = blocks(b, "UPDATE r03_orders SET status = status WHERE id = 2")
        ca.execute("ROLLBACK")
        matrix[name] = (sel, upd)
        check(f"{name}: 取るロック", locks == EXPECTED_LOCKS[name], str(sorted(locks)))
        check(f"{name}: 同時の SELECT {'待つ' if EXPECTED_BLOCK[name][0] else '待たない'} / UPDATE {'待つ' if EXPECTED_BLOCK[name][1] else '待たない'}",
              matrix[name] == EXPECTED_BLOCK[name], str(matrix[name]))
    ca.execute("ALTER TABLE r03_orders ADD CONSTRAINT r03_orders_customer_fk FOREIGN KEY (customer_id) REFERENCES customers (id) NOT VALID")
    ca.execute("BEGIN")
    ca.execute("ALTER TABLE r03_orders VALIDATE CONSTRAINT r03_orders_customer_fk")
    locks = my_locks(ca)
    sel = blocks(b, "SELECT status FROM r03_orders WHERE id = 1")
    upd = blocks(b, "UPDATE r03_orders SET status = status WHERE id = 2")
    ca.execute("ROLLBACK")
    matrix["VALIDATE CONSTRAINT"] = (sel, upd)
    check("VALIDATE CONSTRAINT: ShareUpdateExclusiveLock で、SELECT も UPDATE も待たない",
          ("r03_orders", "ShareUpdateExclusiveLock") in locks and (sel, upd) == (False, False), f"{sorted(locks)} {(sel, upd)}")
    ca.execute("ALTER TABLE r03_orders DROP CONSTRAINT r03_orders_customer_fk")
    for sql in ("CREATE INDEX CONCURRENTLY r03_x ON r03_orders (customer_id)", "VACUUM r03_orders"):
        ca.execute("BEGIN")
        try:
            ca.execute(sql)
            ok = False
        except errors.ActiveSqlTransaction:
            ok = True
        ca.execute("ROLLBACK")
        check(f"トランザクションの中では実行できない: {sql.split(' r03')[0]}", ok)
    a.close(), b.close()
    return matrix


def verify_cic_and_rewrite() -> None:
    c = conn()
    cur = c.cursor()
    cur.execute("SET client_min_messages = warning")
    try:
        cur.execute("CREATE UNIQUE INDEX CONCURRENTLY r03_orders_customer_uniq ON r03_orders (customer_id)")
        err = None
    except errors.UniqueViolation as e:
        err = e
    cur.execute("SELECT indisvalid FROM pg_index WHERE indexrelid = 'r03_orders_customer_uniq'::regclass")
    check("失敗した CREATE UNIQUE INDEX CONCURRENTLY は INVALID のインデックスを残す", err is not None and cur.fetchone() == (False,))
    cur.execute("DROP INDEX CONCURRENTLY r03_orders_customer_uniq")
    try:
        cur.execute("CREATE UNIQUE INDEX r03_orders_customer_uniq ON r03_orders (customer_id)")
    except errors.UniqueViolation:
        pass
    check("CONCURRENTLY なしで失敗した場合は何も残らない", one(cur, "SELECT count(*) FROM pg_index WHERE indrelid = 'r03_orders'::regclass") == 1)

    def files():
        cur.execute("SELECT (SELECT relfilenode FROM pg_class WHERE relname = 'r03_orders'), "
                    "(SELECT relfilenode FROM pg_class WHERE relname = 'r03_orders_pkey')")
        return cur.fetchone()

    steps = [
        ("ADD COLUMN（既定値なし）", "ALTER TABLE r03_orders ADD COLUMN note text", False),
        ("ADD COLUMN ... NOT NULL DEFAULT false", "ALTER TABLE r03_orders ADD COLUMN is_gift boolean NOT NULL DEFAULT false", False),
        ("ADD COLUMN ... DEFAULT clock_timestamp()", "ALTER TABLE r03_orders ADD COLUMN imported_at timestamptz DEFAULT clock_timestamp()", True),
        ("integer → bigint", "ALTER TABLE r03_orders ALTER COLUMN customer_id TYPE bigint", True),
        ("text → varchar(20)", "ALTER TABLE r03_orders ALTER COLUMN status TYPE varchar(20)", True),
        ("varchar(20) → varchar(30)", "ALTER TABLE r03_orders ALTER COLUMN status TYPE varchar(30)", False),
    ]
    for label, sql, rewrite in steps:
        before = files()
        cur.execute(sql)
        after = files()
        check(f"{label}: {'書き換える（relfilenode が変わる）' if rewrite else '書き換えない'}",
              (before != after) == rewrite and (before[1] != after[1]) == rewrite, f"{before} -> {after}")
        if label.startswith("ADD COLUMN ... NOT NULL"):
            cur.execute("SELECT atthasmissing, attmissingval::text FROM pg_attribute WHERE attrelid = 'r03_orders'::regclass AND attname = 'is_gift'")
            check("定数の既定値はカタログ（attmissingval）に持つ", cur.fetchone() == (True, "{f}"))
    c.close()


class Background:
    def __init__(self, c, sql):
        self.error = None
        self.pid = c.info.backend_pid
        self.t = threading.Thread(target=self._run, args=(c, sql), daemon=True)
        self.t.start()

    def _run(self, c, sql):
        try:
            c.cursor().execute(sql)
        except Exception as e:  # noqa: BLE001
            self.error = e

    def join(self, timeout=30):
        self.t.join(timeout)
        return not self.t.is_alive()


def waiting(mon, pid, timeout=5.0) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        if one(mon, "SELECT coalesce(wait_event_type, '') FROM pg_stat_activity WHERE pid = %s", (pid,)) == "Lock":
            return True
        time.sleep(0.05)
    return False


def verify_instant_ddl_queue() -> None:
    a, b, c, m = conn(), conn(), conn(), conn()
    ca, cb, cm = a.cursor(), b.cursor(), m.cursor()
    ca.execute("BEGIN")
    ca.execute("SELECT count(*) FROM r03_orders WHERE id <= 1000")
    bgb = Background(b, "ALTER TABLE r03_orders ADD COLUMN memo text")
    wb = waiting(cm, bgb.pid)
    bgc = Background(c, "SELECT status FROM r03_orders WHERE id = 1")
    wc = waiting(cm, bgc.pid)
    blocked_by = list(one(cm, "SELECT pg_blocking_pids(%s)", (bgc.pid,)))
    check("書き換えなしの ADD COLUMN でも長いトランザクションの後ろで待ち、その後ろの 1 行の SELECT も待つ",
          wb and wc and blocked_by == [bgb.pid], str(blocked_by))
    ca.execute("COMMIT")
    bgb.join(), bgc.join()
    check("長いトランザクションが終わると両方進む", bgb.error is None and bgc.error is None)
    ca.execute("BEGIN")
    ca.execute("SELECT count(*) FROM r03_orders WHERE id <= 1000")
    cb.execute("SET lock_timeout = '1s'")
    try:
        cb.execute("ALTER TABLE r03_orders ADD COLUMN memo2 text")
        err = None
    except errors.LockNotAvailable as e:
        err = e
    bgc = Background(c, "SELECT status FROM r03_orders WHERE id = 1")
    check("lock_timeout = 1s の DDL はあきらめ、後ろの SELECT は待たない", err is not None and bgc.join(3) and bgc.error is None)
    ca.execute("COMMIT")
    cb.execute("ALTER TABLE r03_orders ADD COLUMN memo2 text")
    check("リトライは通る", one(cm, "SELECT count(*) FROM pg_attribute WHERE attrelid = 'r03_orders'::regclass AND attname = 'memo2'") == 1)
    for x in (a, b, c, m):
        x.close()


def verify_hot_queue_join_unused() -> None:
    c = conn()
    cur = c.cursor()
    cur.execute("SET client_min_messages = warning")
    for t, idx in (("r03_hot_pk", None), ("r03_hot_date", "ordered_at"), ("r03_hot_status", "status")):
        cur.execute(f"DROP TABLE IF EXISTS {t}")
        cur.execute(f"CREATE TABLE {t} (LIKE orders) WITH (autovacuum_enabled = off, fillfactor = 90)")
        cur.execute(f"INSERT INTO {t} SELECT * FROM orders WHERE id <= 200000 ORDER BY id")
        cur.execute(f"ALTER TABLE {t} ADD PRIMARY KEY (id)")
        if idx:
            cur.execute(f"CREATE INDEX {t}_{idx}_idx ON {t} ({idx})")
        cur.execute(f"VACUUM (ANALYZE) {t}")
    for t in ("r03_hot_pk", "r03_hot_date", "r03_hot_status"):
        cur.execute(f"UPDATE {t} SET status = 'pending' WHERE id % 20 = 0")
    cur.execute("SELECT pg_stat_force_next_flush()")
    time.sleep(0.3)
    cur.execute("SELECT relname, n_tup_hot_upd FROM pg_stat_user_tables WHERE relname LIKE 'r03_hot_%'")
    hot = dict(cur.fetchall())
    already = one(cur, "SELECT count(*) FROM orders WHERE id <= 200000 AND id % 20 = 0 AND status = 'pending'")
    check("HOT: 主キーだけ・更新しない列のインデックスは全件 HOT、更新する列（status）のインデックスがあると"
          "値が変わらなかった行（もともと pending）だけが HOT",
          hot == {"r03_hot_pk": 10000, "r03_hot_date": 10000, "r03_hot_status": already} and already == 1366, f"{hot} {already}")

    cur.execute("DROP TABLE IF EXISTS r03_jobs")
    cur.execute("CREATE TABLE r03_jobs (id integer PRIMARY KEY, status text NOT NULL, payload text NOT NULL)")
    cur.execute("INSERT INTO r03_jobs SELECT g, CASE WHEN g > 99900 THEN 'queued' ELSE 'done' END, 'job-' || g FROM generate_series(1, 100000) AS g")
    cur.execute("VACUUM (ANALYZE) r03_jobs")
    q = "SELECT id FROM r03_jobs WHERE status = 'queued' ORDER BY id LIMIT 1 FOR UPDATE SKIP LOCKED"
    p1 = explain(cur, q)
    scan1 = find_nodes(p1, "Index Scan")
    cur.execute("CREATE INDEX r03_jobs_queued_idx ON r03_jobs (id) WHERE status = 'queued'")
    p2 = explain(cur, q)
    scan2 = find_nodes(p2, "Index Scan")
    check("キュー: 部分インデックスなしは主キーを読みながら 99,900 行を読み飛ばす（LockRows の下）",
          "LockRows" in node_types(p1) and scan1 and scan1[0]["Index Name"] == "r03_jobs_pkey"
          and scan1[0].get("Rows Removed by Filter") == 99900, str(node_types(p1)))
    check("キュー: 部分インデックスがあるとそれを使い、読み飛ばしがない",
          scan2 and scan2[0]["Index Name"] == "r03_jobs_queued_idx" and scan2[0].get("Rows Removed by Filter", 0) == 0)
    check("部分インデックスは 2 ページ", one(cur, "SELECT pg_relation_size('r03_jobs_queued_idx') / 8192") == 2)

    # 統計のずれ
    setup_orders(cur)
    cur.execute("CREATE INDEX r03_orders_status_idx ON r03_orders (status)")
    cur.execute("ANALYZE r03_orders")
    sql = "SELECT count(*) FROM r03_orders WHERE status = 'cancelled'"

    def est_act(plan):
        leaf = [n for n in find_nodes(plan, "Index Only Scan") + find_nodes(plan, "Bitmap Heap Scan") + find_nodes(plan, "Seq Scan")]
        n = leaf[0]
        return n["Plan Rows"] * (n.get("Workers Planned", 0) or 1), actual_total_rows(n), n["Node Type"]

    e0, a0, n0 = est_act(explain(cur, sql))
    cur.execute("UPDATE r03_orders SET status = 'cancelled' WHERE id % 5 = 0")
    cur.execute("SELECT pg_stat_force_next_flush()")
    time.sleep(0.3)
    mod = one(cur, "SELECT n_mod_since_analyze FROM pg_stat_user_tables WHERE relname = 'r03_orders'")
    e1, a1, n1 = est_act(explain(cur, sql))
    cur.execute("ANALYZE r03_orders")
    plan2 = explain(cur, sql)
    bitmap = find_nodes(plan2, "Bitmap Index Scan")
    check("更新前: キャンセル 43,478 件で見積もりとの差は 2 倍以内", a0 == 43478 and 0.5 < e0 / a0 < 2, f"{e0} {a0} {n0}")
    check("20万行の一括更新: n_mod_since_analyze = 200000（自動 ANALYZE の発火点 100,050 を超える）", mod == 200000)
    check("ANALYZE 前: 実際は 234,783 件なのに見積もりは半分未満のまま", a1 == 234783 and e1 / a1 < 0.5, f"{e1} {a1} {n1}")
    check("ANALYZE 後: 見積もりが実際に近づき（2 倍以内）、Index Only Scan から Bitmap Heap Scan に変わる",
          n1 == "Index Only Scan" and bitmap and 0.5 < bitmap[0]["Plan Rows"] / 234783 < 2 and "Bitmap Heap Scan" in node_types(plan2),
          f"{node_types(plan2)}")

    # FOR UPDATE OF
    cur.execute("DROP TABLE IF EXISTS r03_customers")
    cur.execute("CREATE TABLE r03_customers (LIKE customers)")
    cur.execute("INSERT INTO r03_customers SELECT * FROM customers ORDER BY id")
    cur.execute("ALTER TABLE r03_customers ADD PRIMARY KEY (id)")
    cur.execute("VACUUM (ANALYZE) r03_customers")
    xmax_sql = ("SELECT (SELECT xmax::text FROM r03_orders WHERE id = %(id)s), "
                "(SELECT c.xmax::text FROM r03_customers AS c JOIN r03_orders AS o ON o.customer_id = c.id WHERE o.id = %(id)s)")
    for oid, of_clause, both in ((1, " OF o", False), (2, "", True)):
        cur.execute("BEGIN")
        q = ("SELECT o.id FROM r03_orders AS o JOIN r03_customers AS c ON c.id = o.customer_id "
             f"WHERE o.id = {oid} FOR UPDATE{of_clause}")
        plan = explain(cur, q, analyze=False)
        cur.execute(q)
        xid = one(cur, "SELECT pg_current_xact_id()::text")
        cur.execute(xmax_sql, {"id": oid})
        ox, cx = cur.fetchone()
        cur.execute("ROLLBACK")
        check(f"FOR UPDATE{of_clause or '（OF なし）'}: 計画の根は LockRows、{'注文の行と顧客の行の両方' if both else '注文の行だけ'}がロックされる",
              plan["Plan"]["Node Type"] == "LockRows" and ox == xid and ((cx == xid) if both else (cx == "0")), f"{ox} {cx} {xid}")

    # 使われていないインデックス
    setup_orders(cur)
    cur.execute("CREATE INDEX r03_orders_customer_idx ON r03_orders (customer_id)")
    cur.execute("CREATE INDEX r03_orders_ordered_at_idx ON r03_orders (ordered_at)")
    for cid in (7920, 15839, 23758):
        cur.execute("SELECT count(*) FROM r03_orders WHERE customer_id = %s", (cid,))
    cur.execute("SELECT pg_stat_force_next_flush()")
    time.sleep(0.3)
    cur.execute("SELECT indexrelname, idx_scan FROM pg_stat_user_indexes WHERE relname = 'r03_orders'")
    scans = dict(cur.fetchall())
    check("idx_scan: customer_id は 3、ordered_at と主キーは 0",
          scans == {"r03_orders_customer_idx": 3, "r03_orders_ordered_at_idx": 0, "r03_orders_pkey": 0}, str(scans))
    cur.execute("DROP INDEX CONCURRENTLY r03_orders_ordered_at_idx")
    c.close()


def verify_mysql() -> None:
    m = mysql_connect()
    cur = m.cursor()
    cur.execute("DROP TABLE IF EXISTS r03_orders")
    cur.execute("CREATE TABLE r03_orders (PRIMARY KEY (id)) AS SELECT * FROM orders WHERE id <= 200000")
    cur.execute("ALTER TABLE r03_orders ADD COLUMN note TEXT, ALGORITHM=INSTANT")
    codes = []
    for alg in ("INSTANT", "INPLACE"):
        try:
            cur.execute(f"ALTER TABLE r03_orders MODIFY customer_id BIGINT NOT NULL, ALGORITHM={alg}")
            codes.append(0)
        except Exception as e:  # noqa: BLE001
            codes.append(e.args[0])
    cur.execute("ALTER TABLE r03_orders MODIFY customer_id BIGINT NOT NULL, ALGORITHM=COPY")
    cur.execute("ALTER TABLE r03_orders ADD INDEX r03_orders_customer_idx (customer_id), ALGORITHM=INPLACE, LOCK=NONE")
    check("MySQL: ADD COLUMN は INSTANT、型変更は INSTANT / INPLACE が 1846 で断られ COPY なら通る、索引追加は INPLACE・LOCK=NONE",
          codes == [1846, 1846], str(codes))
    cur.execute("DROP TABLE r03_orders")
    m.close()


def main() -> None:
    matrix = verify_lock_modes()
    verify_cic_and_rewrite()
    verify_instant_ddl_queue()
    verify_hot_queue_join_unused()
    verify_mysql()
    print("\n実測: トランザクションの中で操作を実行したまま、別の接続の SELECT（主キーで 1 行）/ UPDATE（別の 1 行）が待つか")
    for name, (sel, upd) in matrix.items():
        print(f"  {name}: SELECT={'待つ' if sel else '待たない'} / UPDATE={'待つ' if upd else '待たない'}")
    with conn() as c:
        c.execute("DROP TABLE IF EXISTS r03_orders, r03_customers, r03_jobs, r03_hot_pk, r03_hot_date, r03_hot_status")
    finish("横断復習③")


if __name__ == "__main__":
    main()

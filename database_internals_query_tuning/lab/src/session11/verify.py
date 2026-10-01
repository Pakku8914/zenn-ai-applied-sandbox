"""S11 ロックと同時実行 — 自己検証。

出発点（tools/reset.sh 直後）から単独で実行する。作業用テーブル s11_products / s11_order_lines / s11_jobs だけを変更する。
2〜4 セッションの実験は psycopg の接続を複数本使い、ブロックする文はスレッドで実行して
pg_stat_activity の wait_event_type = 'Lock'・pg_blocking_pids()・pg_locks の granted で「誰が誰を待っているか」を確かめる。
すべての接続に statement_timeout / lock_timeout を掛けてあるので、想定外の待ちが起きてもハングしない。
判定に使うのは、待ったかどうか・待ち先・ロックの種類・エラーの種類（SQLSTATE）・結果の値だけ（時間は使わない）。
"""

from __future__ import annotations

import threading
import time

import psycopg
from psycopg import errors

from labcheck import check, finish, mysql_connect

TIMEOUTS = "-c statement_timeout=30s -c lock_timeout=20s"


def conn() -> psycopg.Connection:
    return psycopg.connect(autocommit=True, options=TIMEOUTS)


def setup(cur) -> None:
    cur.execute("SET client_min_messages = warning")
    cur.execute("DROP TABLE IF EXISTS s11_order_lines, s11_products, s11_jobs")
    cur.execute("CREATE TABLE s11_products AS SELECT * FROM products")
    cur.execute("ALTER TABLE s11_products ADD PRIMARY KEY (id)")
    cur.execute("CREATE TABLE s11_order_lines (id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, "
                "product_id integer NOT NULL REFERENCES s11_products (id), quantity integer NOT NULL)")
    cur.execute("CREATE TABLE s11_jobs (id integer PRIMARY KEY, status text NOT NULL, worker text)")
    cur.execute("INSERT INTO s11_jobs SELECT g, 'queued', NULL FROM generate_series(1, 10) AS g")
    cur.execute("VACUUM (ANALYZE) s11_products, s11_jobs")
    cur.execute("RESET client_min_messages")


def one(cur, sql: str, params=None):
    cur.execute(sql, params)
    return cur.fetchone()[0]


class Background:
    """ブロックするかもしれない文を別スレッドで実行する。"""

    def __init__(self, c: psycopg.Connection, *sqls: str):
        self.error: Exception | None = None
        self.result = None
        self.pid = c.info.backend_pid
        self.t = threading.Thread(target=self._run, args=(c, sqls), daemon=True)
        self.t.start()

    def _run(self, c, sqls):
        try:
            cur = c.cursor()
            for sql in sqls:
                cur.execute(sql)
            self.result = cur.fetchall() if cur.description else cur.rowcount
        except Exception as e:  # noqa: BLE001 — エラーの種類を後で判定する
            self.error = e

    def join(self, timeout=25):
        self.t.join(timeout)
        return not self.t.is_alive()

    @property
    def running(self):
        return self.t.is_alive()


def wait_event(mon, pid: int, timeout=5.0) -> tuple[str, str] | None:
    """pid が Lock 待ちになるまで待ち、(wait_event_type, wait_event) を返す。"""
    end = time.time() + timeout
    while time.time() < end:
        mon.execute("SELECT coalesce(wait_event_type, ''), coalesce(wait_event, '') FROM pg_stat_activity WHERE pid = %s", (pid,))
        row = mon.fetchone()
        if row and row[0] == "Lock":
            return row
        time.sleep(0.05)
    return None


def blocking(mon, pid: int) -> list[int]:
    return list(one(mon, "SELECT pg_blocking_pids(%s)", (pid,)))


def rel_locks(mon, pid: int, rel: str) -> list[tuple[str, bool]]:
    mon.execute("SELECT mode, granted FROM pg_locks WHERE pid = %s AND locktype = 'relation' AND relation = %s::regclass "
                "ORDER BY mode", (pid, rel))
    return mon.fetchall()


def verify_row_locks() -> None:
    a, b, m = conn(), conn(), conn()
    ca, cb, cm = a.cursor(), b.cursor(), m.cursor()
    setup(ca)

    # 01: 同じ行の更新は待つ
    ca.execute("BEGIN")
    ca.execute("UPDATE s11_products SET stock = stock - 1 WHERE id = 1")
    bg = Background(b, "UPDATE s11_products SET stock = stock - 1 WHERE id = 1")
    ev = wait_event(cm, bg.pid)
    check("同じ行の UPDATE は待つ（wait_event = transactionid）", ev == ("Lock", "transactionid"), str(ev))
    check("pg_blocking_pids は待たせている側の pid を返す", blocking(cm, bg.pid) == [a.info.backend_pid])
    ca.execute("COMMIT")
    bg.join()
    check("先がコミットすると後の UPDATE が進み、在庫は 13 → 11", bg.error is None and one(cm, "SELECT stock FROM s11_products WHERE id = 1") == 11)

    ca.execute("BEGIN")
    ca.execute("UPDATE s11_products SET stock = stock - 1 WHERE id = 1")
    cb.execute("SET lock_timeout = '2s'")
    try:
        cb.execute("UPDATE s11_products SET stock = stock - 1 WHERE id = 1")
        err = None
    except errors.LockNotAvailable as e:
        err = e
    cb.execute("SET lock_timeout = '20s'")
    check("lock_timeout = 2s: 55P03 canceling statement due to lock timeout",
          err is not None and "lock timeout" in str(err), str(err))
    ca.execute("ROLLBACK")

    # 02: FOR UPDATE / FOR SHARE / NOWAIT
    setup(ca)
    ca.execute("BEGIN")
    ca.execute("SELECT id FROM s11_products WHERE id = 1 FOR UPDATE")
    check("FOR UPDATE されている行も、普通の SELECT は待たずに読める", one(cb, "SELECT stock FROM s11_products WHERE id = 1") == 13)
    results = {}
    for mode in ("FOR UPDATE", "FOR SHARE", "FOR KEY SHARE"):
        try:
            cb.execute(f"SELECT id FROM s11_products WHERE id = 1 {mode} NOWAIT")
            results[mode] = "取れた"
        except errors.LockNotAvailable:
            results[mode] = "55P03"
    check("FOR UPDATE されている行に対して、FOR UPDATE / FOR SHARE / FOR KEY SHARE の NOWAIT はすべて 55P03",
          set(results.values()) == {"55P03"}, str(results))
    ca.execute("COMMIT")
    ca.execute("BEGIN")
    ca.execute("SELECT id FROM s11_products WHERE id = 1 FOR SHARE")
    cb.execute("BEGIN")
    cb.execute("SELECT id FROM s11_products WHERE id = 1 FOR SHARE NOWAIT")
    check("FOR SHARE どうしは両立する", cb.fetchone() == (1,))
    cb.execute("SET LOCAL lock_timeout = '1s'")
    try:
        cb.execute("UPDATE s11_products SET stock = stock - 1 WHERE id = 1")
        err = None
    except errors.LockNotAvailable as e:
        err = e
    check("FOR SHARE されている行の UPDATE は待つ（1 秒の lock_timeout で 55P03）", err is not None)
    cb.execute("ROLLBACK")
    ca.execute("COMMIT")

    # 03: 外部キーの検査（FOR KEY SHARE）
    ca.execute("BEGIN")
    ca.execute("UPDATE s11_products SET stock = stock - 1 WHERE id = 1")
    bg = Background(b, "INSERT INTO s11_order_lines (product_id, quantity) VALUES (1, 2)")
    done = bg.join(3)
    check("キー以外の列を UPDATE 中の行を参照する INSERT は待たない（FOR KEY SHARE と両立）", done and bg.error is None, str(bg.error))
    ca.execute("COMMIT")
    ca.execute("BEGIN")
    ca.execute("DELETE FROM s11_products WHERE id = 3")
    bg = Background(b, "INSERT INTO s11_order_lines (product_id, quantity) VALUES (3, 1)")
    ev = wait_event(cm, bg.pid)
    check("DELETE 中の行を参照する INSERT は外部キーの検査で待つ", ev == ("Lock", "transactionid"), str(ev))
    ca.execute("ROLLBACK")
    bg.join()
    check("DELETE を取り消すと INSERT が進む（明細 2 行）",
          bg.error is None and one(cm, "SELECT count(*) FROM s11_order_lines") == 2)

    # 04: SKIP LOCKED
    take = "SELECT id FROM s11_jobs WHERE status = 'queued' ORDER BY id LIMIT 1 FOR UPDATE"
    ca.execute("BEGIN")
    ja = one(ca, take + " SKIP LOCKED")
    cb.execute("BEGIN")
    jb = one(cb, take + " SKIP LOCKED")
    check("SKIP LOCKED: ワーカーAがジョブ1、ワーカーBは待たずにジョブ2を取る", (ja, jb) == (1, 2), f"{ja} {jb}")
    ca.execute("UPDATE s11_jobs SET status = 'done', worker = 'A' WHERE id = 1")
    ca.execute("COMMIT")
    cb.execute("UPDATE s11_jobs SET status = 'done', worker = 'B' WHERE id = 2")
    cb.execute("COMMIT")
    ca.execute("BEGIN")
    ja = one(ca, take + " SKIP LOCKED")
    b.cursor().execute("BEGIN")
    bg = Background(b, take)
    ev = wait_event(cm, bg.pid)
    check("SKIP LOCKED なしでは、ロック中のジョブ3を待つ", ja == 3 and ev is not None, f"{ja} {ev}")
    ca.execute("UPDATE s11_jobs SET status = 'done', worker = 'A' WHERE id = 3")
    ca.execute("COMMIT")
    bg.join()
    check("待っていた行が条件に合わなくなったので、次のジョブ4を返す", bg.result == [(4,)], str(bg.result))
    cb.execute("ROLLBACK")
    a.close(), b.close(), m.close()


def verify_chain_and_deadlock() -> None:
    a, b, c, m = conn(), conn(), conn(), conn()
    ca, cb, cc, cm = a.cursor(), b.cursor(), c.cursor(), m.cursor()
    setup(ca)

    # 05: 待機の連鎖
    ca.execute("BEGIN")
    ca.execute("UPDATE s11_products SET stock = stock - 1 WHERE id = 1")
    cb.execute("BEGIN")
    cb.execute("UPDATE s11_products SET stock = stock - 1 WHERE id = 2")
    bgb = Background(b, "UPDATE s11_products SET stock = stock - 1 WHERE id = 1")
    wait_event(cm, bgb.pid)
    cc.execute("BEGIN")
    bgc = Background(c, "UPDATE s11_products SET stock = stock - 1 WHERE id = 2")
    wait_event(cm, bgc.pid)
    pa, pb, pc = a.info.backend_pid, b.info.backend_pid, c.info.backend_pid
    chain = (blocking(cm, pa), blocking(cm, pb), blocking(cm, pc))
    check("待機の連鎖: C は B を、B は A を待ち、A は誰も待たない", chain == ([], [pa], [pb]), str(chain))
    ca.execute("COMMIT")
    bgb.join()
    check("根元の A がコミットすると B が進み、C はまだ B を待つ", bgb.error is None and bgc.running and blocking(cm, pc) == [pb])
    cb.execute("COMMIT")
    bgc.join()
    cc.execute("COMMIT")
    check("連鎖がほどけて在庫は 11 / 24", one(cm, "SELECT array_agg(stock ORDER BY id) FROM s11_products WHERE id IN (1, 2)") == [11, 24])

    # 同じ行に 3 人目: tuple ロックの行列
    ca.execute("BEGIN")
    ca.execute("UPDATE s11_products SET stock = stock - 1 WHERE id = 1")
    cb.execute("BEGIN")
    bgb = Background(b, "UPDATE s11_products SET stock = stock - 1 WHERE id = 1")
    evb = wait_event(cm, bgb.pid)
    cc.execute("BEGIN")
    bgc = Background(c, "UPDATE s11_products SET stock = stock - 1 WHERE id = 1")
    evc = wait_event(cm, bgc.pid)
    check("同じ行の 2 人目は transactionid、3 人目は tuple を待ち、3 人目の待ち先は 2 人目",
          evb[1] == "transactionid" and evc[1] == "tuple" and blocking(cm, pc) == [pb], f"{evb} {evc} {blocking(cm, pc)}")
    ca.execute("COMMIT")
    bgb.join()
    cb.execute("COMMIT")
    bgc.join()
    cc.execute("COMMIT")

    # 06: デッドロック
    setup(ca)
    cm.execute("SHOW deadlock_timeout")
    check("deadlock_timeout は既定の 1s", cm.fetchone()[0] == "1s")
    ca.execute("BEGIN")
    ca.execute("UPDATE s11_products SET stock = stock - 1 WHERE id = 1")
    cb.execute("BEGIN")
    cb.execute("UPDATE s11_products SET stock = stock - 1 WHERE id = 2")
    bga = Background(a, "UPDATE s11_products SET stock = stock - 1 WHERE id = 2")
    wait_event(cm, bga.pid)
    time.sleep(1.5)  # A の待ちが deadlock_timeout を過ぎてから B を待たせる（検出するのは後から待った B になる）
    try:
        cb.execute("UPDATE s11_products SET stock = stock - 1 WHERE id = 1")
        err = None
    except errors.DeadlockDetected as e:
        err = e
    check("逆順の更新で 40P01 deadlock detected（後から待った B が取り消される）", err is not None and err.sqlstate == "40P01", str(err))
    if err is not None:
        detail = err.diag.message_detail or ""
        check("DETAIL に両方の pid と「blocked by process」が出る",
              str(a.info.backend_pid) in detail and str(b.info.backend_pid) in detail and "blocked by process" in detail, detail)
    cb.execute("ROLLBACK")
    bga.join()
    check("残った A の UPDATE は進む", bga.error is None)
    ca.execute("COMMIT")
    check("A の 2 行だけが減る（12 / 25）", one(cm, "SELECT array_agg(stock ORDER BY id) FROM s11_products WHERE id IN (1, 2)") == [12, 25])

    # 07: id の昇順でロックすればデッドロックしない
    setup(ca)
    ca.execute("BEGIN")
    ca.execute("SELECT id FROM s11_products WHERE id IN (1, 2) ORDER BY id FOR UPDATE")
    ca.execute("UPDATE s11_products SET stock = stock - 1 WHERE id = 1")
    cb.execute("BEGIN")
    bgb = Background(b, "SELECT id FROM s11_products WHERE id IN (2, 1) ORDER BY id FOR UPDATE",
                     "UPDATE s11_products SET stock = stock - 1 WHERE id = 2",
                     "UPDATE s11_products SET stock = stock - 1 WHERE id = 1")
    ev = wait_event(cm, bgb.pid)
    time.sleep(1.5)
    ca.execute("UPDATE s11_products SET stock = stock - 1 WHERE id = 2")
    ca.execute("COMMIT")
    bgb.join()
    cb.execute("COMMIT")
    check("id の昇順で FOR UPDATE を取ると、B は待つだけでデッドロックにならない（在庫 11 / 24）",
          ev is not None and bgb.error is None
          and one(cm, "SELECT array_agg(stock ORDER BY id) FROM s11_products WHERE id IN (1, 2)") == [11, 24], str(bgb.error))
    a.close(), b.close(), c.close(), m.close()


def verify_ddl_locks() -> None:
    a, b, c, m = conn(), conn(), conn(), conn()
    ca, cb, cc, cm = a.cursor(), b.cursor(), c.cursor(), m.cursor()
    setup(ca)
    pa, pb, pc = a.info.backend_pid, b.info.backend_pid, c.info.backend_pid

    # 08: DDL の行列
    ca.execute("BEGIN")
    ca.execute("SELECT count(*) FROM s11_products")
    bgb = Background(b, "ALTER TABLE s11_products ADD COLUMN note text")
    wait_event(cm, bgb.pid)
    bgc = Background(c, "SELECT count(*) FROM s11_products")
    evc = wait_event(cm, bgc.pid)
    check("ALTER TABLE は AccessExclusiveLock を待つ", rel_locks(cm, pb, "s11_products") == [("AccessExclusiveLock", False)])
    check("その後ろの普通の SELECT も AccessShareLock を待ち、待ち先は ALTER TABLE",
          evc == ("Lock", "relation") and rel_locks(cm, pc, "s11_products") == [("AccessShareLock", False)]
          and blocking(cm, pc) == [pb], f"{evc} {blocking(cm, pc)}")
    ca.execute("COMMIT")
    bgb.join(), bgc.join()
    check("A がコミットすると ALTER TABLE → SELECT の順に進む", bgb.error is None and bgc.result == [(5000,)])

    ca.execute("BEGIN")
    ca.execute("SELECT count(*) FROM s11_products")
    cb.execute("SET lock_timeout = '2s'")
    try:
        cb.execute("ALTER TABLE s11_products ADD COLUMN note2 text")
        err = None
    except errors.LockNotAvailable as e:
        err = e
    check("lock_timeout = 2s の DDL は 55P03 であきらめる", err is not None)
    bgc = Background(c, "SELECT count(*) FROM s11_products")
    check("DDL があきらめたあとは、普通の SELECT は待たない", bgc.join(3) and bgc.result == [(5000,)])
    cb.execute("SET lock_timeout = 0")
    cb.execute("SET statement_timeout = '2s'")
    msgs = []
    for sql in ("ALTER TABLE s11_products ADD COLUMN note2 text", "SELECT pg_sleep(3)"):
        try:
            cb.execute(sql)
            msgs.append("完了")
        except errors.QueryCanceled as e:
            msgs.append(str(e).splitlines()[0])
    check("statement_timeout はロック待ちの DDL も pg_sleep(3) も 57014 で切る",
          msgs == ["canceling statement due to statement timeout"] * 2, str(msgs))
    cb.execute("SET statement_timeout = '30s'")
    cb.execute("SET lock_timeout = '1s'")
    cb.execute("SELECT pg_sleep(1.5)")
    check("lock_timeout は pg_sleep(1.5) を切らない（ロックの待ちにしか効かない）", cb.fetchone() == ("",))
    cb.execute("SET lock_timeout = '20s'")
    ca.execute("COMMIT")

    # 09: CREATE INDEX と CONCURRENTLY
    setup(ca)
    ca.execute("BEGIN")
    ca.execute("CREATE INDEX s11_products_category_idx ON s11_products (category)")
    check("CREATE INDEX はテーブルに ShareLock を取る", ("ShareLock", True) in rel_locks(cm, pa, "s11_products"))
    check("CREATE INDEX の最中も SELECT は待たない", one(cb, "SELECT count(*) FROM s11_products WHERE category = '書籍'") == 1250)
    bgb = Background(b, "UPDATE s11_products SET stock = stock - 1 WHERE id = 1")
    ev = wait_event(cm, bgb.pid)
    check("CREATE INDEX の最中の UPDATE は待つ（RowExclusiveLock が ShareLock と衝突）",
          ev == ("Lock", "relation") and rel_locks(cm, pb, "s11_products") == [("RowExclusiveLock", False)], str(ev))
    ca.execute("ROLLBACK")
    bgb.join()

    ca.execute("BEGIN")
    ca.execute("UPDATE s11_products SET stock = stock - 1 WHERE id = 1")
    bgc = Background(c, "CREATE INDEX CONCURRENTLY s11_products_category_idx ON s11_products (category)")
    ev = wait_event(cm, bgc.pid)
    cm.execute("SELECT phase, current_locker_pid FROM pg_stat_progress_create_index WHERE pid = %s", (pc,))
    progress = cm.fetchone()
    check("CONCURRENTLY は先に始まった書き込みトランザクションを待つ（virtualxid・waiting for writers before build）",
          ev == ("Lock", "virtualxid") and progress == ("waiting for writers before build", pa), f"{ev} {progress}")
    check("CONCURRENTLY が持つのは ShareUpdateExclusiveLock", rel_locks(cm, pc, "s11_products") == [("ShareUpdateExclusiveLock", True)])
    bgb = Background(b, "UPDATE s11_products SET stock = stock - 1 WHERE id = 2")
    check("CONCURRENTLY の途中でも別の行の UPDATE は待たない", bgb.join(3) and bgb.error is None)
    ca.execute("COMMIT")
    bgc.join()
    check("A がコミットすると CONCURRENTLY が終わり、インデックスは有効",
          bgc.error is None and one(cm, "SELECT indisvalid FROM pg_index WHERE indexrelid = 's11_products_category_idx'::regclass"))

    ca.execute("BEGIN")
    ca.execute("UPDATE s11_products SET stock = stock - 1 WHERE id = 1")
    bgc = Background(c, "CREATE INDEX s11_products_name_idx ON s11_products (name)")
    wait_event(cm, bgc.pid)
    bgb = Background(b, "UPDATE s11_products SET stock = stock - 1 WHERE id = 2")
    ev = wait_event(cm, bgb.pid)
    check("書き込み中に普通の CREATE INDEX を打つと、CREATE INDEX は ShareLock を待ち、後ろの UPDATE まで待たされる",
          rel_locks(cm, pc, "s11_products") == [("ShareLock", False)] and ev == ("Lock", "relation")
          and blocking(cm, pb) == [pc] and blocking(cm, pc) == [pa], f"{ev} {blocking(cm, pb)} {blocking(cm, pc)}")
    ca.execute("COMMIT")
    bgc.join(), bgb.join()
    check("A がコミットすると CREATE INDEX と UPDATE が進む", bgc.error is None and bgb.error is None)
    a.close(), b.close(), c.close(), m.close()


def verify_mysql() -> None:
    m1, m2, m3, mm = mysql_connect(), mysql_connect(), mysql_connect(), mysql_connect()
    c1, c2, c3, cm = m1.cursor(), m2.cursor(), m3.cursor(), mm.cursor()
    c1.execute("DROP TABLE IF EXISTS s11_products")
    c1.execute("CREATE TABLE s11_products (PRIMARY KEY (id)) AS SELECT * FROM products")
    for c in (c1, c2, c3):
        c.execute("SET SESSION innodb_lock_wait_timeout = 10")
        c.execute("SET SESSION lock_wait_timeout = 10")
    c1.execute("START TRANSACTION")
    c1.execute("UPDATE s11_products SET stock = stock - 1 WHERE id = 1")
    c2.execute("START TRANSACTION")
    c2.execute("UPDATE s11_products SET stock = stock - 1 WHERE id = 2")
    res = {}

    def a_update():
        try:
            c1.execute("UPDATE s11_products SET stock = stock - 1 WHERE id = 2")
            res["a"] = "ok"
        except Exception as e:  # noqa: BLE001
            res["a"] = e.args[0]

    t = threading.Thread(target=a_update, daemon=True)
    t.start()
    time.sleep(0.5)
    try:
        c2.execute("UPDATE s11_products SET stock = stock - 1 WHERE id = 1")
        err = None
    except Exception as e:  # noqa: BLE001
        err = e
    t.join(10)
    check("MySQL: 逆順の更新は 1213 Deadlock found（InnoDB は待ちの輪を即座に検出）", err is not None and err.args[0] == 1213, str(err))
    check("MySQL: 残った側の UPDATE は進む", res.get("a") == "ok", str(res))
    c1.execute("COMMIT")
    c2.execute("ROLLBACK")
    cm.execute("SHOW ENGINE INNODB STATUS")
    status = cm.fetchone()[2]
    check("MySQL: SHOW ENGINE INNODB STATUS に LATEST DETECTED DEADLOCK と WE ROLL BACK TRANSACTION が出る",
          "LATEST DETECTED DEADLOCK" in status and "WE ROLL BACK TRANSACTION" in status)

    # メタデータロックの行列
    c1.execute("START TRANSACTION")
    c1.execute("SELECT COUNT(*) FROM s11_products")
    c1.fetchall()
    states = {}

    def run(c, key, sql):
        try:
            c.execute(sql)
            states[key] = "ok"
        except Exception as e:  # noqa: BLE001
            states[key] = e.args[0]

    tb = threading.Thread(target=run, args=(c2, "b", "ALTER TABLE s11_products ADD COLUMN note TEXT"), daemon=True)
    tb.start()
    time.sleep(0.7)
    tc = threading.Thread(target=run, args=(c3, "c", "SELECT COUNT(*) FROM s11_products"), daemon=True)
    tc.start()
    time.sleep(0.7)
    cm.execute("SELECT id, state FROM information_schema.processlist WHERE id IN (%s, %s)", (m2.thread_id(), m3.thread_id()))
    waits = {row[0]: row[1] for row in cm.fetchall()}
    check("MySQL: ALTER TABLE も後ろの SELECT も Waiting for table metadata lock",
          waits == {m2.thread_id(): "Waiting for table metadata lock", m3.thread_id(): "Waiting for table metadata lock"}, str(waits))
    c1.execute("COMMIT")
    tb.join(10), tc.join(10)
    check("MySQL: A がコミットすると両方進む", states == {"b": "ok", "c": "ok"}, str(states))
    c1.execute("START TRANSACTION")
    c1.execute("SELECT COUNT(*) FROM s11_products")
    c1.fetchall()
    c2.execute("SET SESSION lock_wait_timeout = 2")
    try:
        c2.execute("ALTER TABLE s11_products ADD COLUMN note2 TEXT")
        err = None
    except Exception as e:  # noqa: BLE001
        err = e
    check("MySQL: lock_wait_timeout = 2 の DDL は 1205 であきらめる", err is not None and err.args[0] == 1205, str(err))
    c1.execute("COMMIT")
    c1.execute("DROP TABLE s11_products")
    for x in (m1, m2, m3, mm):
        x.close()


def main() -> None:
    verify_row_locks()
    verify_chain_and_deadlock()
    verify_ddl_locks()
    verify_mysql()
    with conn() as c:
        c.execute("DROP TABLE IF EXISTS s11_order_lines, s11_products, s11_jobs")
    finish("S11 ロックと同時実行")


if __name__ == "__main__":
    main()

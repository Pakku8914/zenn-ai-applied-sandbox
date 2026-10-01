"""S12 VACUUM と肥大化 — 自己検証。

出発点（tools/reset.sh 直後）から単独で実行する。作業用テーブル s12_orders（100万行）・s12_av・s12_ff100/s12_ff90・s12_tail だけを変更する。
判定に使うのは、ページ数・不要行の数・空き領域の割合・インデックスのリーフ密度（pgstattuple / pgstatindex。データが決定的なので一定）、
ロックの種類と待ったかどうか、autovacuum が走ったか（pg_stat_user_tables）、凍結の印（t_infomask）だけ。時間は判定に使わない。
autovacuum の発火は autovacuum_naptime（10 秒）ごとなので、この検証は 2〜3 分かかる。
"""

from __future__ import annotations

import threading
import time

import psycopg
from psycopg import errors

from labcheck import check, finish, mysql_connect

TIMEOUTS = "-c statement_timeout=120s -c lock_timeout=60s"


def conn() -> psycopg.Connection:
    return psycopg.connect(autocommit=True, options=TIMEOUTS)


def one(cur, sql: str, params=None):
    cur.execute(sql, params)
    return cur.fetchone()[0]


def measure(cur) -> dict:
    cur.execute("""
        SELECT pg_relation_size('s12_orders') / 8192, t.tuple_count, t.dead_tuple_count, t.free_percent,
               pg_relation_size('s12_orders_pkey') / 8192, i.leaf_pages, i.avg_leaf_density
        FROM pgstattuple('s12_orders') AS t, pgstatindex('s12_orders_pkey') AS i""")
    keys = ("pages", "live", "dead", "free_pct", "pkey_pages", "leaf_pages", "leaf_density")
    return dict(zip(keys, cur.fetchone()))


def table_stats(cur, rel: str) -> tuple:
    cur.execute("SELECT pg_stat_force_next_flush()")
    time.sleep(0.2)
    cur.execute("SELECT n_tup_upd, n_tup_hot_upd, n_dead_tup, autovacuum_count FROM pg_stat_user_tables WHERE relname = %s", (rel,))
    return cur.fetchone()


class Background:
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
        except Exception as e:  # noqa: BLE001
            self.error = e

    def join(self, timeout=60):
        self.t.join(timeout)
        return not self.t.is_alive()


def wait_lock(mon, pid: int, timeout=5.0) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        if one(mon, "SELECT coalesce(wait_event_type, '') FROM pg_stat_activity WHERE pid = %s", (pid,)) == "Lock":
            return True
        time.sleep(0.05)
    return False


def rel_locks(mon, pid: int) -> dict:
    mon.execute("SELECT relation::regclass::text, mode, granted FROM pg_locks WHERE pid = %s AND locktype = 'relation' "
                "AND relation::regclass::text LIKE 's12_orders%%'", (pid,))
    return {(r, m): g for r, m, g in mon.fetchall()}


def create_copy(cur, name: str, where: str = "", options: str = "autovacuum_enabled = off") -> None:
    cur.execute("SET client_min_messages = warning")
    cur.execute(f"DROP TABLE IF EXISTS {name}")
    cur.execute("RESET client_min_messages")
    cur.execute(f"CREATE TABLE {name} (LIKE orders) WITH ({options})")
    cur.execute(f"INSERT INTO {name} SELECT * FROM orders {where} ORDER BY id")
    # INSERT の統計が VACUUM の後に反映されると「VACUUM 後の INSERT」と数えられ、自動の VACUUM が余分に走るので先に反映させる
    cur.execute("SELECT pg_stat_force_next_flush()")
    time.sleep(0.5)


def verify_bloat() -> None:
    c = conn()
    cur = c.cursor()
    create_copy(cur, "s12_orders")
    cur.execute("ALTER TABLE s12_orders ADD PRIMARY KEY (id)")
    cur.execute("VACUUM (ANALYZE) s12_orders")
    base = measure(cur)
    check("出発点: 8197 ページ・不要行 0・主キーのリーフ密度は約 90%",
          base["pages"] == 8197 and base["dead"] == 0 and 88 < base["leaf_density"] < 92, str(base))

    cur.execute("UPDATE s12_orders SET status = status")
    after1 = measure(cur)
    upd, hot, _, _ = table_stats(cur, "s12_orders")
    check("値を変えない全件 UPDATE でもテーブルは約 2 倍・不要行 100 万",
          after1["pages"] >= 2 * base["pages"] - 10 and after1["dead"] == 1000000 and after1["live"] == 1000000, str(after1))
    check("満杯のページなので HOT 更新はほぼ 0（1% 未満）", upd == 1000000 and hot < 10000, f"upd={upd} hot={hot}")
    check("主キーのインデックスも約 2 倍", after1["pkey_pages"] >= 1.9 * base["pkey_pages"], str(after1))

    cur.execute("VACUUM s12_orders")
    vac1 = measure(cur)
    check("VACUUM: 不要行は 0 になるが、ページ数は変わらない（空きが約半分）",
          vac1["dead"] == 0 and vac1["pages"] == after1["pages"] and vac1["free_pct"] > 45, str(vac1))
    check("VACUUM 後: インデックスの大きさは変わらず、リーフ密度が半分ほどに下がる",
          vac1["pkey_pages"] == after1["pkey_pages"] and vac1["leaf_density"] < 55, str(vac1))

    cur.execute("UPDATE s12_orders SET status = status")
    after2 = measure(cur)
    check("VACUUM 後の 2 回目の全件 UPDATE は空きを再利用し、テーブルもインデックスも大きくならない",
          after2["pages"] == vac1["pages"] and after2["pkey_pages"] == vac1["pkey_pages"], str(after2))
    cur.execute("VACUUM s12_orders")
    vac2 = measure(cur)
    cur.execute("SELECT max((ctid::text::point)[0])::int FROM s12_orders")
    last = cur.fetchone()[0]
    check("2 回目の VACUUM でも、末尾のページに行が残っているのでページ数は変わらない",
          vac2["pages"] == vac1["pages"] and last == vac2["pages"] - 1, f"{vac2} last={last}")

    cur.execute("REINDEX INDEX CONCURRENTLY s12_orders_pkey")
    rei = measure(cur)
    check("REINDEX CONCURRENTLY: 主キーは出発点の大きさ・密度に戻る",
          rei["leaf_pages"] == base["leaf_pages"] and rei["leaf_density"] > 88, str(rei))
    node0 = one(cur, "SELECT relfilenode FROM pg_class WHERE relname = 's12_orders'")
    cur.execute("VACUUM FULL s12_orders")
    full = measure(cur)
    node1 = one(cur, "SELECT relfilenode FROM pg_class WHERE relname = 's12_orders'")
    check("VACUUM FULL: 8197 ページに戻り、ファイルが作り直される（relfilenode が変わる）",
          full["pages"] == base["pages"] and full["free_pct"] < 1 and node0 != node1, f"{full} {node0}->{node1}")
    c.close()


def verify_locks() -> None:
    a, b, cc, m = conn(), conn(), conn(), conn()
    ca, cb, ccur, cm = a.cursor(), b.cursor(), cc.cursor(), m.cursor()
    pa, pb, pc = a.info.backend_pid, b.info.backend_pid, cc.info.backend_pid

    # 普通の VACUUM（わざと遅くする）は読み書きを止めない
    ca.execute("UPDATE s12_orders SET status = status WHERE id <= 200000")
    ca.execute("SET vacuum_cost_delay = '100ms'")
    ca.execute("SET vacuum_cost_limit = 10")
    bg = Background(a, "VACUUM s12_orders")
    time.sleep(1.5)
    locks = rel_locks(cm, pa)
    phase = one(cm, "SELECT phase FROM pg_stat_progress_vacuum WHERE pid = %s", (pa,))
    check("VACUUM が持つのは ShareUpdateExclusiveLock（pg_stat_progress_vacuum の phase は scanning heap）",
          locks.get(("s12_orders", "ShareUpdateExclusiveLock")) is True and phase == "scanning heap", f"{locks} {phase}")
    t0 = Background(b, "SELECT count(*) FROM s12_orders WHERE id <= 10", "UPDATE s12_orders SET status = status WHERE id = 1")
    check("VACUUM の最中でも SELECT と UPDATE は待たない", t0.join(5) and t0.error is None)
    a.cancel_safe()
    bg.join()
    check("Ctrl+C（キャンセル）で VACUUM は canceling statement due to user request で止まる",
          isinstance(bg.error, errors.QueryCanceled) and "user request" in str(bg.error), str(bg.error))
    ca.execute("RESET vacuum_cost_delay")
    ca.execute("RESET vacuum_cost_limit")

    # VACUUM FULL は ACCESS EXCLUSIVE を待ち、後ろの SELECT も待たせる
    ca.execute("BEGIN")
    ca.execute("SELECT count(*) FROM s12_orders")
    bgb = Background(b, "VACUUM FULL s12_orders")
    wait_lock(cm, pb)
    bgc = Background(cc, "SELECT count(*) FROM s12_orders WHERE id <= 10")
    waited = wait_lock(cm, pc)
    check("VACUUM FULL は AccessExclusiveLock を待ち、その後ろの SELECT も待たされる（待ち先は VACUUM FULL）",
          rel_locks(cm, pb).get(("s12_orders", "AccessExclusiveLock")) is False and waited
          and list(one(cm, "SELECT pg_blocking_pids(%s)", (pc,))) == [pb])
    ca.execute("COMMIT")
    bgb.join(), bgc.join()
    check("A がコミットすると VACUUM FULL → SELECT の順に進む", bgb.error is None and bgc.result == [(10,)])

    # REINDEX（CONCURRENTLY なし）はインデックスに ACCESS EXCLUSIVE を取り、計画を立てるだけの SELECT も止める
    ca.execute("BEGIN")
    ca.execute("REINDEX INDEX s12_orders_pkey")
    locks = rel_locks(cm, pa)
    check("REINDEX: テーブルに ShareLock、インデックスに AccessExclusiveLock",
          locks == {("s12_orders", "ShareLock"): True, ("s12_orders_pkey", "AccessExclusiveLock"): True}, str(locks))
    bgb = Background(b, "SELECT status FROM s12_orders WHERE id = 1")
    bgc = Background(cc, "SELECT count(*) FROM s12_orders")
    wb, wc = wait_lock(cm, pb), wait_lock(cm, pc)
    check("REINDEX 中は、主キーで引く SELECT も全件の集計も、インデックスの AccessShareLock を待つ",
          wb and wc and rel_locks(cm, pb).get(("s12_orders_pkey", "AccessShareLock")) is False
          and rel_locks(cm, pc).get(("s12_orders_pkey", "AccessShareLock")) is False)
    ca.execute("COMMIT")
    bgb.join(), bgc.join()
    check("REINDEX のコミット後に両方進む", bgb.error is None and bgc.error is None)

    # REINDEX CONCURRENTLY は書き込みトランザクションの終わりを待つが、SELECT は止めない
    ca.execute("BEGIN")
    ca.execute("UPDATE s12_orders SET status = status WHERE id = 1")
    bgb = Background(b, "REINDEX INDEX CONCURRENTLY s12_orders_pkey")
    wait_lock(cm, pb)
    time.sleep(0.3)
    phase = one(cm, "SELECT phase FROM pg_stat_progress_create_index WHERE pid = %s", (pb,))
    locks = rel_locks(cm, pb)
    check("REINDEX CONCURRENTLY: ShareUpdateExclusiveLock を持ち、waiting for writers before build",
          locks.get(("s12_orders", "ShareUpdateExclusiveLock")) is True and phase == "waiting for writers before build",
          f"{locks} {phase}")
    t0 = Background(cc, "SELECT status FROM s12_orders WHERE id = 2")
    check("その間も主キーで引く SELECT は待たない", t0.join(5) and t0.error is None)
    ca.execute("COMMIT")
    bgb.join()
    check("書き込みが終わると REINDEX CONCURRENTLY も終わる", bgb.error is None)
    for x in (a, b, cc, m):
        x.close()


def wait_until(cur, rel: str, cond, timeout: float) -> tuple:
    end = time.time() + timeout
    st = table_stats(cur, rel)
    while time.time() < end:
        st = table_stats(cur, rel)
        if cond(st):
            return st
        time.sleep(1)
    return st


def verify_autovacuum() -> None:
    a, b = conn(), conn()
    ca, cb = a.cursor(), b.cursor()
    create_copy(ca, "s12_av", "WHERE id <= 100000")
    ca.execute("ALTER TABLE s12_av ADD PRIMARY KEY (id)")
    ca.execute("VACUUM (ANALYZE) s12_av")
    ca.execute("ALTER TABLE s12_av SET (autovacuum_enabled = on, autovacuum_vacuum_scale_factor = 0, autovacuum_vacuum_threshold = 1000)")
    ca.execute("UPDATE s12_av SET status = status WHERE id <= 900")
    time.sleep(25)
    st = table_stats(ca, "s12_av")
    check("発火点（1000 行）未満の 900 行では、25 秒待っても autovacuum は走らない", st[3] == 0 and st[2] == 900, str(st))
    ca.execute("UPDATE s12_av SET status = status WHERE id > 900 AND id <= 1100")
    st = wait_until(ca, "s12_av", lambda s: s[3] >= 1 and s[2] == 0, 60)
    check("1100 行（発火点超え）で autovacuum が走り、不要行が 0 になる", st[3] >= 1 and st[2] == 0, str(st))

    cb.execute("BEGIN ISOLATION LEVEL REPEATABLE READ")
    cb.execute("SELECT count(*) FROM s12_av")
    before = table_stats(ca, "s12_av")[3]
    ca.execute("UPDATE s12_av SET status = status WHERE id <= 5000")
    st = wait_until(ca, "s12_av", lambda s: s[3] >= before + 2, 60)
    check("長時間トランザクションがあると、autovacuum が何度走っても（2 回以上）不要行 5000 は減らない",
          st[3] >= before + 2 and st[2] >= 5000, f"before={before} {st}")
    cb.execute("COMMIT")
    st = wait_until(ca, "s12_av", lambda s: s[2] == 0, 60)
    check("トランザクションを閉じると、次の autovacuum で回収される", st[2] == 0, str(st))
    a.close(), b.close()


def verify_fillfactor_truncate_freeze() -> None:
    c = conn()
    cur = c.cursor()
    create_copy(cur, "s12_ff100", "WHERE id <= 200000")
    create_copy(cur, "s12_ff90", "WHERE id <= 200000", "autovacuum_enabled = off, fillfactor = 90")
    pages = {}
    for t in ("s12_ff100", "s12_ff90"):
        cur.execute(f"ALTER TABLE {t} ADD PRIMARY KEY (id)")
        cur.execute(f"VACUUM (ANALYZE) {t}")
        before = one(cur, f"SELECT pg_relation_size('{t}') / 8192")
        cur.execute(f"UPDATE {t} SET status = 'pending' WHERE id % 20 = 0")
        pages[t] = (before, one(cur, f"SELECT pg_relation_size('{t}') / 8192"))
    s100, s90 = table_stats(cur, "s12_ff100"), table_stats(cur, "s12_ff90")
    check("5% の行の更新: fillfactor 100 は HOT 0、fillfactor 90 はすべて HOT",
          (s100[0], s100[1], s90[0], s90[1]) == (10000, 0, 10000, 10000), f"{s100} {s90}")
    check("fillfactor 90 のテーブルは更新してもページ数が増えず、fillfactor 100 は増える",
          pages["s12_ff90"][0] == pages["s12_ff90"][1] and pages["s12_ff100"][1] > pages["s12_ff100"][0], str(pages))

    create_copy(cur, "s12_tail", "WHERE id <= 200000")
    cur.execute("VACUUM s12_tail")
    p0 = one(cur, "SELECT pg_relation_size('s12_tail') / 8192")
    cur.execute("DELETE FROM s12_tail WHERE id <= 100000")
    cur.execute("VACUUM s12_tail")
    p1 = one(cur, "SELECT pg_relation_size('s12_tail') / 8192")
    cur.execute("DELETE FROM s12_tail WHERE id > 150000")
    cur.execute("VACUUM s12_tail")
    p2 = one(cur, "SELECT pg_relation_size('s12_tail') / 8192")
    check("VACUUM は末尾の空ページだけを切り詰める（1640 → 先頭側を消しても 1640 → 末尾側を消すと 1230）",
          (p0, p1, p2) == (1640, 1640, 1230), f"{p0} {p1} {p2}")

    # 凍結
    cur.execute("ALTER TABLE s12_orders SET (autovacuum_enabled = off)")
    cur.execute("UPDATE s12_orders SET status = status WHERE id <= 10000")
    flags_sql = """
        SELECT count(*) FILTER (WHERE 'HEAP_XMIN_FROZEN' = ANY (f.combined_flags))
        FROM s12_orders AS o,
             LATERAL (SELECT (ctid::text::point)[0]::int AS blk, (ctid::text::point)[1]::int AS lp) AS p,
             LATERAL (SELECT h.t_infomask, h.t_infomask2 FROM heap_page_items(get_raw_page('s12_orders', p.blk)) AS h
                      WHERE h.lp = p.lp) AS h,
             LATERAL heap_tuple_infomask_flags(h.t_infomask, h.t_infomask2) AS f
        WHERE o.id <= 3"""
    before = one(cur, flags_sql)
    cur.execute("VACUUM (FREEZE) s12_orders")
    after = one(cur, flags_sql)
    age = one(cur, "SELECT age(relfrozenxid) FROM pg_class WHERE relname = 's12_orders'")
    dbage = one(cur, "SELECT age(datfrozenxid) FROM pg_database WHERE datname = current_database()")
    check("VACUUM (FREEZE): 更新したばかりの行（凍結 0/3）が HEAP_XMIN_FROZEN（3/3）になる", (before, after) == (0, 3), f"{before} {after}")
    check("VACUUM (FREEZE) 後の age(relfrozenxid) はデータベースの age より小さい（ほぼ 0）", age < dbage and age < 1000, f"{age} {dbage}")
    check("周回までの目安: 2^31 = 2147483648、autovacuum_freeze_max_age = 2 億",
          one(cur, "SELECT (2^31)::bigint") == 2147483648 and one(cur, "SELECT current_setting('autovacuum_freeze_max_age')::int") == 200000000)
    c.close()


def verify_mysql() -> None:
    m1, m2 = mysql_connect(), mysql_connect()
    c1, c2 = m1.cursor(), m2.cursor()
    c1.execute("DROP TABLE IF EXISTS s12_orders")
    c1.execute("CREATE TABLE s12_orders (PRIMARY KEY (id)) AS SELECT * FROM orders WHERE id <= 200000")
    size_sql = "SELECT file_size FROM information_schema.innodb_tablespaces WHERE name = CONCAT(DATABASE(), '/s12_orders')"
    c1.execute(size_sql)
    s0 = c1.fetchone()[0]
    changed_same = c1.execute("UPDATE s12_orders SET status = status")
    changed_all = c1.execute("UPDATE s12_orders SET ordered_at = ordered_at + INTERVAL 1 SECOND")
    c1.execute(size_sql)
    s1 = c1.fetchone()[0]
    check("MySQL: 値を変えない UPDATE は 0 行変更、全件の値を変えても表領域ファイルの大きさは変わらない",
          changed_same == 0 and changed_all == 200000 and s0 == s1, f"{changed_same} {changed_all} {s0} {s1}")
    hist = "SELECT count FROM information_schema.innodb_metrics WHERE name = 'trx_rseg_history_len'"
    c2.execute("START TRANSACTION WITH CONSISTENT SNAPSHOT")
    c2.execute("SELECT COUNT(*) FROM s12_orders")
    c2.fetchall()
    c1.execute(hist)
    h0 = c1.fetchone()[0]
    for i in range(1, 2001):
        c1.execute("UPDATE s12_orders SET customer_id = customer_id + 1 WHERE id = %s", (i,))
    c1.execute(hist)
    h1 = c1.fetchone()[0]
    check("MySQL: スナップショットを持つトランザクションが開いている間、2000 回の更新で history list length が 1500 以上増える",
          h1 - h0 >= 1500, f"{h0} -> {h1}")
    c2.execute("COMMIT")
    # purge はインスタンス全体で動き、他のデータベースの長いトランザクションにも止められるので、減り方は判定に使わず表示だけする
    time.sleep(5)
    c1.execute(hist)
    print(f"参考  MySQL: COMMIT の 5 秒後の history list length — {h1} -> {c1.fetchone()[0]}")
    c1.execute("DROP TABLE s12_orders")
    m1.close(), m2.close()


def main() -> None:
    verify_bloat()
    verify_locks()
    verify_autovacuum()
    verify_fillfactor_truncate_freeze()
    verify_mysql()
    with conn() as c:
        c.execute("DROP TABLE IF EXISTS s12_orders, s12_av, s12_ff100, s12_ff90, s12_tail")
    finish("S12 VACUUM と肥大化")


if __name__ == "__main__":
    main()

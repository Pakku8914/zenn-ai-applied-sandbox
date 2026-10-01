"""S10 トランザクションと MVCC — 自己検証。

出発点（tools/reset.sh 直後）から単独で実行する。作業用テーブル s10_products / s10_oncall / s10_vac だけを変更する。
2 セッションの実験は psycopg の接続を 2〜3 本使い、ブロックする文はスレッドで実行して
pg_stat_activity の wait_event_type = 'Lock' で「待っている」ことを確かめる。
すべての接続に statement_timeout / lock_timeout を掛けてあるので、想定外の待ちが起きてもハングしない。
判定に使うのは結果の値・エラーの種類（SQLSTATE）・VACUUM が報告する行数だけ（トランザクション番号の値そのものは使わない）。
最後に「どの分離レベルでどの異常が起きたか」の表を表示する。
"""

from __future__ import annotations

import re
import threading
import time

import psycopg
from psycopg import errors

from labcheck import check, finish, mysql_connect, pg_connect

LEVELS = {"RC": "READ COMMITTED", "RR": "REPEATABLE READ", "SER": "SERIALIZABLE"}
TIMEOUTS = "-c statement_timeout=20s -c lock_timeout=15s"


def conn() -> psycopg.Connection:
    return psycopg.connect(autocommit=True, options=TIMEOUTS)


def setup(cur) -> None:
    cur.execute("SET client_min_messages = warning")
    cur.execute("DROP TABLE IF EXISTS s10_products, s10_oncall")
    cur.execute("CREATE TABLE s10_products AS SELECT id, name, category, stock FROM products WHERE id <= 5")
    cur.execute("ALTER TABLE s10_products ADD PRIMARY KEY (id)")
    cur.execute("CREATE TABLE s10_oncall (doctor text PRIMARY KEY, on_call boolean NOT NULL)")
    cur.execute("INSERT INTO s10_oncall VALUES ('佐藤', true), ('鈴木', true)")
    cur.execute("RESET client_min_messages")


def one(cur, sql: str, params=None):
    cur.execute(sql, params)
    return cur.fetchone()[0]


class Background:
    """ブロックするかもしれない文を別スレッドで実行する。"""

    def __init__(self, c: psycopg.Connection, sql: str):
        self.error: Exception | None = None
        self.rowcount = None
        self.pid = c.info.backend_pid
        self.t = threading.Thread(target=self._run, args=(c, sql), daemon=True)
        self.t.start()

    def _run(self, c, sql):
        try:
            cur = c.cursor()
            cur.execute(sql)
            self.rowcount = cur.rowcount
        except Exception as e:  # noqa: BLE001 — エラーの種類を後で判定する
            self.error = e

    def join(self, timeout=20):
        self.t.join(timeout)
        return not self.t.is_alive()


def waiting_on_lock(mon, pid: int, timeout=5.0) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        if one(mon, "SELECT coalesce(wait_event_type, '') FROM pg_stat_activity WHERE pid = %s", (pid,)) == "Lock":
            return True
        time.sleep(0.05)
    return False


def dirty_read(level_sql: str) -> bool:
    a, b = conn(), conn()
    ca, cb = a.cursor(), b.cursor()
    setup(ca)
    ca.execute("BEGIN")
    ca.execute("UPDATE s10_products SET stock = 0 WHERE id = 1")
    cb.execute(f"BEGIN ISOLATION LEVEL {level_sql}")
    seen = one(cb, "SELECT stock FROM s10_products WHERE id = 1")
    cb.execute("COMMIT")
    ca.execute("ROLLBACK")
    a.close(), b.close()
    return seen == 0


def nonrepeatable(level: str) -> bool:
    a, b = conn(), conn()
    ca, cb = a.cursor(), b.cursor()
    setup(ca)
    cb.execute(f"BEGIN ISOLATION LEVEL {LEVELS[level]}")
    first = one(cb, "SELECT stock FROM s10_products WHERE id = 1")
    ca.execute("UPDATE s10_products SET stock = stock - 1 WHERE id = 1")
    second = one(cb, "SELECT stock FROM s10_products WHERE id = 1")
    cb.execute("COMMIT")
    a.close(), b.close()
    return first != second


def phantom(level: str) -> bool:
    a, b = conn(), conn()
    ca, cb = a.cursor(), b.cursor()
    setup(ca)
    cb.execute(f"BEGIN ISOLATION LEVEL {LEVELS[level]}")
    first = one(cb, "SELECT count(*) FROM s10_products WHERE category = '書籍'")
    ca.execute("INSERT INTO s10_products VALUES (6, '商品6', '書籍', 78)")
    second = one(cb, "SELECT count(*) FROM s10_products WHERE category = '書籍'")
    cb.execute("COMMIT")
    a.close(), b.close()
    return first != second


def lost_update(level: str) -> tuple[str, int, bool]:
    """読んで → 計算して → 値を書く。戻り値: (結果, 最終在庫, B が行ロックを待ったか)"""
    a, b, m = conn(), conn(), conn()
    ca, cb, cm = a.cursor(), b.cursor(), m.cursor()
    setup(ca)
    ca.execute(f"BEGIN ISOLATION LEVEL {LEVELS[level]}")
    va = one(ca, "SELECT stock FROM s10_products WHERE id = 1")
    cb.execute(f"BEGIN ISOLATION LEVEL {LEVELS[level]}")
    vb = one(cb, "SELECT stock FROM s10_products WHERE id = 1")
    ca.execute(f"UPDATE s10_products SET stock = {va - 1} WHERE id = 1")
    bg = Background(b, f"UPDATE s10_products SET stock = {vb - 1} WHERE id = 1")
    waited = waiting_on_lock(cm, bg.pid)
    ca.execute("COMMIT")
    bg.join()
    if bg.error is None:
        cb.execute("COMMIT")
        result = "起きる"
    else:
        result = f"エラー（{bg.error.sqlstate}: {str(bg.error).splitlines()[0]}）"
        cb.execute("ROLLBACK")
    final = one(cm, "SELECT stock FROM s10_products WHERE id = 1")
    a.close(), b.close(), m.close()
    return result, final, waited


def write_skew(level: str, both_update_first: bool = False) -> tuple[str, int]:
    """戻り値: (結果, 残った当直の人数)"""
    a, b = conn(), conn()
    ca, cb = a.cursor(), b.cursor()
    setup(ca)
    for c in (ca, cb):
        c.execute(f"BEGIN ISOLATION LEVEL {LEVELS[level]}")
        assert one(c, "SELECT count(*) FROM s10_oncall WHERE on_call") == 2
    err = None
    try:
        ca.execute("UPDATE s10_oncall SET on_call = false WHERE doctor = '佐藤'")
        if both_update_first:
            cb.execute("UPDATE s10_oncall SET on_call = false WHERE doctor = '鈴木'")
            ca.execute("COMMIT")
            cb.execute("COMMIT")
        else:
            ca.execute("COMMIT")
            cb.execute("UPDATE s10_oncall SET on_call = false WHERE doctor = '鈴木'")
            cb.execute("COMMIT")
    except errors.SerializationFailure as e:
        err = e
        cb.execute("ROLLBACK")
    left = one(ca, "SELECT count(*) FROM s10_oncall WHERE on_call")
    a.close(), b.close()
    if err is None:
        return "起きる", left
    detail = (err.diag.message_detail or "").strip()
    return f"エラー（{err.sqlstate}: {detail}）", left


def go_off_call_with_retry(c: psycopg.Connection, doctor: str, before_commit=None, max_tries=3) -> tuple[bool, int]:
    """Serializable のリトライ付き処理。戻り値: (抜けたか, 試行回数)"""
    cur = c.cursor()
    for attempt in range(1, max_tries + 1):
        try:
            cur.execute("BEGIN ISOLATION LEVEL SERIALIZABLE")
            n = one(cur, "SELECT count(*) FROM s10_oncall WHERE on_call")
            went = False
            if n >= 2:
                if before_commit and attempt == 1:
                    before_commit()
                cur.execute("UPDATE s10_oncall SET on_call = false WHERE doctor = %s", (doctor,))
                went = True
            cur.execute("COMMIT")
            return went, attempt
        except errors.SerializationFailure:
            cur.execute("ROLLBACK")
    raise RuntimeError("リトライ上限")


def vacuum_verbose(c: psycopg.Connection, table: str) -> tuple[int, int, int]:
    msgs: list[str] = []
    def handler(d):
        msgs.append(d.message_primary or "")

    c.add_notice_handler(handler)
    c.cursor().execute(f"VACUUM (VERBOSE) {table}")
    c.remove_notice_handler(handler)
    text = "\n".join(msgs)
    m = re.search(r"tuples: (\d+) removed, (\d+) remain, (\d+) are dead but not yet removable", text)
    return tuple(int(x) for x in m.groups())


def verify_xmin_xmax() -> None:
    c = conn()
    cur = c.cursor()
    setup(cur)
    xmin0 = one(cur, "SELECT xmin::text FROM s10_products WHERE id = 1")
    check("作った直後の行は xmax = 0", one(cur, "SELECT count(*) FROM s10_products WHERE xmax::text <> '0'") == 0)
    cur.execute("BEGIN")
    xid = one(cur, "SELECT pg_current_xact_id()::text")
    cur.execute("UPDATE s10_products SET stock = stock - 1 WHERE id = 1")
    cur.execute("SELECT xmin::text, ctid::text FROM s10_products WHERE id = 1")
    new_xmin, new_ctid = cur.fetchone()
    cur.execute("COMMIT")
    check("UPDATE 後に見える版の xmin は更新したトランザクションの番号", new_xmin == xid, f"{new_xmin} / {xid}")
    check("新しい版は (0,6) に置かれる（5 行の小さな表なので同じページ）", new_ctid == "(0,6)", new_ctid)
    cur.execute("SELECT lp, t_xmin::text, t_xmax::text, t_ctid::text FROM heap_page_items(get_raw_page('s10_products', 0)) "
                "WHERE lp IN (1, 6) ORDER BY lp")
    rows = cur.fetchall()
    check("古い版（lp=1）の t_xmax と新しい版（lp=6）の t_xmin が同じ番号・古い版の t_ctid が新しい版を指す",
          rows == [(1, xmin0, xid, "(0,6)"), (6, xid, "0", "(0,6)")], str(rows))

    cur.execute("BEGIN")
    cur.execute("DELETE FROM s10_products WHERE id = 5")
    del_xid = one(cur, "SELECT pg_current_xact_id()::text")
    cur.execute("ROLLBACK")
    cur.execute("SELECT t_xmax::text, pg_xact_status(t_xmax::text::xid8) FROM heap_page_items(get_raw_page('s10_products', 0)) WHERE lp = 5")
    t_xmax, status = cur.fetchone()
    check("ROLLBACK した DELETE の番号は t_xmax に残り、状態は aborted", t_xmax == del_xid and status == "aborted", f"{t_xmax} {status}")
    check("ROLLBACK した行は見える", one(cur, "SELECT count(*) FROM s10_products WHERE id = 5") == 1)

    # 2 セッション：コミット前の更新は他のセッションには古い版で見える
    setup(cur)
    b = conn()
    cb = b.cursor()
    cur.execute("BEGIN")
    a_xid = one(cur, "SELECT pg_current_xact_id()::text")
    cur.execute("UPDATE s10_products SET stock = 0 WHERE id = 1")
    cb.execute("SELECT stock, xmax::text FROM s10_products WHERE id = 1")
    stock, xmax = cb.fetchone()
    check("コミット前: 他のセッションは待たずに古い版（stock=13）を読み、その xmax は更新中のトランザクションの番号",
          stock == 13 and xmax == a_xid, f"stock={stock} xmax={xmax}")
    cb.execute("INSERT INTO s10_products VALUES (6, '商品6', '書籍', 78)")
    snap = one(cb, "SELECT pg_current_snapshot()::text")
    xip = snap.split(":")[2].split(",") if snap.split(":")[2] else []
    check("他のセッションのスナップショットの実行中一覧（xip）に更新中の番号が入る", a_xid in xip, snap)
    check("pg_xact_status は in progress", one(cb, "SELECT pg_xact_status(xmax::text::xid8) FROM s10_products WHERE id = 1") == "in progress")
    cur.execute("COMMIT")
    check("コミット後は新しい版（stock=0）が見える", one(cb, "SELECT stock FROM s10_products WHERE id = 1") == 0)
    b.close()

    # 行ロックだけでも xmax が入る
    setup(cur)
    cur.execute("BEGIN")
    lock_xid = one(cur, "SELECT pg_current_xact_id()::text")
    cur.execute("SELECT * FROM s10_products WHERE id = 2 FOR UPDATE")
    cur.execute("SELECT xmax::text, ctid::text FROM s10_products WHERE id = 2")
    lx, lctid = cur.fetchone()
    cur.execute("COMMIT")
    check("FOR UPDATE だけで xmax に番号が入り、ctid は変わらない", lx == lock_xid and lctid == "(0,2)", f"{lx} {lctid}")
    cur.execute("UPDATE s10_products SET stock = stock - 1 WHERE id = 3")
    cur.execute("SELECT lp, 'HEAP_XMAX_LOCK_ONLY' = ANY(f.raw_flags) FROM heap_page_items(get_raw_page('s10_products', 0)) AS h, "
                "LATERAL heap_tuple_infomask_flags(h.t_infomask, h.t_infomask2) AS f WHERE lp IN (2, 3) ORDER BY lp")
    flags = dict(cur.fetchall())
    check("ロックだけの行（lp=2）には HEAP_XMAX_LOCK_ONLY、更新された古い版（lp=3）には無い", flags == {2: True, 3: False}, str(flags))
    cur.execute("SELECT f.raw_flags FROM heap_page_items(get_raw_page('orders', 0)) AS h, "
                "LATERAL heap_tuple_infomask_flags(h.t_infomask, h.t_infomask2) AS f WHERE lp = 1")
    oflags = cur.fetchone()[0]
    check("シードした orders の行の xmax は外部キー検査の KEY SHARE ロックの印",
          "HEAP_XMAX_KEYSHR_LOCK" in oflags and "HEAP_XMAX_LOCK_ONLY" in oflags, str(oflags))
    c.close()


def verify_anomalies() -> dict:
    table: dict[str, dict[str, str]] = {}
    table["ダーティリード"] = {}
    for lv, sql in [("RU", "READ UNCOMMITTED"), ("RC", LEVELS["RC"]), ("RR", LEVELS["RR"]), ("SER", LEVELS["SER"])]:
        table["ダーティリード"][lv] = "起きる" if dirty_read(sql) else "起きない"
    check("ダーティリードはどの分離レベルでも起きない（READ UNCOMMITTED を含む）",
          set(table["ダーティリード"].values()) == {"起きない"}, str(table["ダーティリード"]))

    table["反復不能読み取り"] = {lv: ("起きる" if nonrepeatable(lv) else "起きない") for lv in LEVELS}
    check("反復不能読み取り: RC で起き、RR・SER では起きない",
          table["反復不能読み取り"] == {"RC": "起きる", "RR": "起きない", "SER": "起きない"}, str(table["反復不能読み取り"]))

    table["ファントム"] = {lv: ("起きる" if phantom(lv) else "起きない") for lv in LEVELS}
    check("ファントム: RC で起き、PostgreSQL の RR・SER では起きない",
          table["ファントム"] == {"RC": "起きる", "RR": "起きない", "SER": "起きない"}, str(table["ファントム"]))

    table["更新の消失"] = {}
    for lv in LEVELS:
        result, final, waited = lost_update(lv)
        table["更新の消失"][lv] = result
        check(f"更新の消失（{lv}）: 後の UPDATE は先の行ロックを待つ", waited)
        if lv == "RC":
            check("RC: 後の UPDATE は成功し、在庫は 12（2 つ売れて 1 つしか減らない）", result == "起きる" and final == 12, f"{result} {final}")
        else:
            check(f"{lv}: 後の UPDATE は 40001 could not serialize access due to concurrent update、在庫は 12",
                  "40001" in result and "concurrent update" in result and final == 12, f"{result} {final}")

    table["書き込みスキュー"] = {}
    for lv in LEVELS:
        result, left = write_skew(lv)
        table["書き込みスキュー"][lv] = result
        if lv == "SER":
            check("SER: 後から書いた側が 40001（read/write dependencies）で失敗し、当直は 1 人残る",
                  "40001" in result and left == 1, f"{result} 残り{left}")
        else:
            check(f"{lv}: 書き込みスキューが起きて当直が 0 人になる", result == "起きる" and left == 0, f"{result} 残り{left}")
    result, left = write_skew("SER", both_update_first=True)
    check("SER（両方が UPDATE してからコミット）: 後のコミットが 40001 で失敗し、当直は 1 人残る",
          "40001" in result and "commit" in result and left == 1, f"{result} 残り{left}")
    table["書き込みスキュー（両方UPDATE後にコミット）"] = {"SER": result}
    return table


def verify_retry() -> None:
    a, b = conn(), conn()
    setup(a.cursor())
    state = {}

    def other_goes_first():
        state["b"] = go_off_call_with_retry(b, "鈴木")

    went_a, tries_a = go_off_call_with_retry(a, "佐藤", before_commit=other_goes_first)
    went_b, tries_b = state["b"]
    left = one(a.cursor(), "SELECT count(*) FROM s10_oncall WHERE on_call")
    check("Serializable のリトライ: 鈴木が先に抜け、佐藤は 1 回目が直列化の失敗 → 2 回目で「1 人しかいない」と分かって抜けない",
          (went_b, tries_b, went_a, tries_a, left) == (True, 1, False, 2, 1), f"鈴木={went_b}/{tries_b}回 佐藤={went_a}/{tries_a}回 残り{left}")
    a.close(), b.close()


def verify_long_transaction() -> None:
    a, b = conn(), conn()
    ca, cb = a.cursor(), b.cursor()
    cb.execute("SET client_min_messages = warning")
    cb.execute("DROP TABLE IF EXISTS s10_vac")
    cb.execute("CREATE TABLE s10_vac WITH (autovacuum_enabled = off) AS SELECT g AS id, 0 AS v FROM generate_series(1, 10000) AS g")
    cb.execute("VACUUM s10_vac")
    cb.execute("RESET client_min_messages")

    ca.execute("BEGIN ISOLATION LEVEL REPEATABLE READ")
    ca.execute("SELECT count(*) FROM s10_vac")
    cb.execute("UPDATE s10_vac SET v = v + 1")
    removed, remain, dead = vacuum_verbose(b, "s10_vac")
    check("RR のトランザクションが開いている間: 0 removed / 10000 are dead but not yet removable", (removed, dead) == (0, 10000), f"{removed} {remain} {dead}")
    cb.execute("SELECT state, backend_xmin IS NOT NULL FROM pg_stat_activity WHERE pid = %s", (a.info.backend_pid,))
    check("犯人の接続は idle in transaction で backend_xmin を持つ", cb.fetchone() == ("idle in transaction", True))
    ca.execute("COMMIT")
    removed, remain, dead = vacuum_verbose(b, "s10_vac")
    check("COMMIT 後: 10000 removed / 0 dead but not yet removable", (removed, dead) == (10000, 0), f"{removed} {remain} {dead}")

    ca.execute("BEGIN")
    ca.execute("SELECT count(*) FROM s10_vac")
    cb.execute("UPDATE s10_vac SET v = v + 1")
    removed, _, dead = vacuum_verbose(b, "s10_vac")
    check("RC で読むだけのトランザクションは回収を止めない（10000 removed）", (removed, dead) == (10000, 0), f"{removed} {dead}")
    cb.execute("SELECT backend_xid, backend_xmin FROM pg_stat_activity WHERE pid = %s", (a.info.backend_pid,))
    check("RC で読むだけ: backend_xid も backend_xmin も NULL", cb.fetchone() == (None, None))
    ca.execute("SELECT pg_current_xact_id()")
    cb.execute("UPDATE s10_vac SET v = v + 1")
    removed, _, dead = vacuum_verbose(b, "s10_vac")
    check("RC でも番号（xid）を持ったトランザクションが開いていると回収できない（10000 dead but not yet removable）",
          (removed, dead) == (0, 10000), f"{removed} {dead}")
    ca.execute("COMMIT")
    a.close(), b.close()


def verify_mysql() -> None:
    m1, m2 = mysql_connect(), mysql_connect()
    c1, c2 = m1.cursor(), m2.cursor()
    c1.execute("SELECT @@transaction_isolation")
    check("MySQL: 既定の分離レベルは REPEATABLE-READ", c1.fetchone()[0] == "REPEATABLE-READ")
    c1.execute("DROP TABLE IF EXISTS s10_products")
    c1.execute("CREATE TABLE s10_products (PRIMARY KEY (id)) AS SELECT id, name, category, stock FROM products WHERE id <= 5")
    for c in (c1, c2):
        c.execute("SET SESSION innodb_lock_wait_timeout = 3")
    # 一貫性読み取りとロック読み取り
    c1.execute("START TRANSACTION")
    c1.execute("SELECT stock FROM s10_products WHERE id = 1")
    c2.execute("UPDATE s10_products SET stock = stock - 1 WHERE id = 1")
    c1.execute("SELECT stock FROM s10_products WHERE id = 1")
    snap = c1.fetchone()[0]
    c1.execute("SELECT stock FROM s10_products WHERE id = 1 FOR UPDATE")
    current = c1.fetchone()[0]
    c1.execute("UPDATE s10_products SET stock = stock - 1 WHERE id = 1")
    c1.execute("COMMIT")
    c1.execute("SELECT stock FROM s10_products WHERE id = 1")
    check("MySQL RR: 普通の SELECT は 13（スナップショット）、FOR UPDATE は 12（最新）、UPDATE はエラーにならず 11",
          (snap, current, c1.fetchone()[0]) == (13, 12, 11))
    # 更新の消失（RR でもエラーにならない）
    c1.execute("START TRANSACTION")
    c1.execute("SELECT stock FROM s10_products WHERE id = 1")
    va = c1.fetchone()[0]
    c2.execute("START TRANSACTION")
    c2.execute("SELECT stock FROM s10_products WHERE id = 1")
    vb = c2.fetchone()[0]
    c1.execute("UPDATE s10_products SET stock = %s WHERE id = 1", (va - 1,))
    res = {}

    def b_update():
        res["n"] = c2.execute("UPDATE s10_products SET stock = %s WHERE id = 1", (vb - 1,))

    t = threading.Thread(target=b_update, daemon=True)
    t.start()
    time.sleep(0.5)
    blocked = t.is_alive()
    c1.execute("COMMIT")
    t.join(10)
    c2.execute("COMMIT")
    c1.execute("SELECT stock FROM s10_products WHERE id = 1")
    final = c1.fetchone()[0]
    check("MySQL RR: 後の UPDATE は待ったあとエラーにならず、在庫は 10（更新の消失が起きる）",
          blocked and final == 10 and "n" in res, f"blocked={blocked} final={final} {res}")
    # ネクストキーロック
    c1.execute("START TRANSACTION")
    c1.execute("SELECT id FROM s10_products WHERE id >= 4 FOR UPDATE")
    try:
        c2.execute("INSERT INTO s10_products VALUES (6, '商品6', '書籍', 78)")
        err = None
    except Exception as e:  # noqa: BLE001
        err = e
    check("MySQL RR: id >= 4 を FOR UPDATE すると、範囲の外の id=6 の INSERT もロック待ちでタイムアウトする（1205）",
          err is not None and err.args[0] == 1205, str(err))
    c2.execute("INSERT INTO s10_products VALUES (0, '商品0', '書籍', 1)")
    check("MySQL RR: 範囲に関係のない id=0 は入る", c2.rowcount == 1)
    c1.execute("ROLLBACK")
    c1.execute("DROP TABLE s10_products")
    m1.close(), m2.close()


def main() -> None:
    verify_xmin_xmax()
    table = verify_anomalies()
    verify_retry()
    verify_long_transaction()
    verify_mysql()

    print("\n実測: どの分離レベルでどの異常が起きたか（RU = READ UNCOMMITTED、PostgreSQL では RC と同じ動作）")
    for anomaly, row in table.items():
        print(f"  {anomaly}: " + " / ".join(f"{lv}={res}" for lv, res in row.items()))
    with pg_connect() as c:
        c.execute("DROP TABLE IF EXISTS s10_products, s10_oncall, s10_vac")
    finish("S10 トランザクションと MVCC")


if __name__ == "__main__":
    main()

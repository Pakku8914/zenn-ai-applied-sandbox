"""S13 書き込みの仕組み — WAL と耐久性 — 自己検証。

出発点（tools/reset.sh 直後）から単独で実行する。作業用テーブル s13_*（4 テーブルのコピーや新しい表）だけを変更する。
判定に使うのは、WAL レコードの種類・数・FPI の数（pg_walinspect・EXPLAIN (WAL)・このセッションの WAL 統計）、
このセッションの fsync 回数（pg_stat_get_backend_io）、ページの LSN、チェックポイントの回数、リレーションの永続性。
時間は「1 行ごとにコミット」と「最後に 1 回だけコミット」の比較（実測で約 30 倍）とインデックスの先/後（約 3.6 倍）にだけ、
緩い条件で使う。full_page_writes / max_wal_size を ALTER SYSTEM で一時的に変えるが、必ず元に戻す（失敗しても reset.sh が戻す）。
"""

from __future__ import annotations

import io
import statistics
import time

import psycopg

from labcheck import check, finish, mysql_connect, pg_connect


def one(cur, sql: str, params=None):
    cur.execute(sql, params)
    return cur.fetchone()[0]


def flush_stats(cur) -> None:
    cur.execute("SELECT pg_stat_force_next_flush()")


def meter(cur) -> dict:
    """このセッションの WAL レコード数・FPI 数・WAL バイト数・WAL の fsync 回数と、WAL の挿入位置。"""
    flush_stats(cur)
    cur.execute("""
        SELECT w.wal_records, w.wal_fpi, w.wal_bytes,
               (SELECT sum(fsyncs) FROM pg_stat_get_backend_io(pg_backend_pid()) WHERE object = 'wal'),
               pg_current_wal_insert_lsn()
        FROM pg_stat_get_backend_wal(pg_backend_pid()) AS w""")
    rec, fpi, nbytes, fsyncs, lsn = cur.fetchone()
    return {"records": rec, "fpi": fpi, "bytes": int(nbytes), "fsyncs": int(fsyncs or 0), "lsn": lsn, "t": time.perf_counter()}


def diff(a: dict, b: dict) -> dict:
    d = {k: b[k] - a[k] for k in ("records", "fpi", "bytes", "fsyncs")}
    d["ms"] = (b["t"] - a["t"]) * 1000
    return d


def fresh(cur, name: str, opts: str = "autovacuum_enabled = off", unlogged: bool = False) -> None:
    cur.execute("SET client_min_messages = warning")
    cur.execute(f"DROP TABLE IF EXISTS {name}")
    cur.execute("RESET client_min_messages")
    cur.execute(f"CREATE {'UNLOGGED ' if unlogged else ''}TABLE {name} (LIKE orders) WITH ({opts})")


def wait_setting(cur, name: str, value: str, timeout: float = 5.0) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        if one(cur, f"SHOW {name}") == value:
            return True
        time.sleep(0.1)
    return False


def explain(cur, sql: str, buffers: bool = False) -> dict:
    """EXPLAIN (ANALYZE, WAL[, BUFFERS], FORMAT JSON)。labcheck.explain には WAL の指定が無いのでここで書く。"""
    cur.execute(f"EXPLAIN (ANALYZE, WAL{', BUFFERS' if buffers else ''}, FORMAT JSON) {sql}")
    return cur.fetchone()[0][0]


def wal_plan(res: dict) -> tuple[int, int, int]:
    p = res["Plan"]
    return p.get("WAL Records", 0), p.get("WAL FPI", 0), p.get("WAL Bytes", 0)


def verify_wal_records(cur) -> None:
    cur.execute("CREATE EXTENSION IF NOT EXISTS pg_walinspect")
    cur.execute("SET client_min_messages = warning")
    cur.execute("DROP TABLE IF EXISTS s13_t")
    cur.execute("RESET client_min_messages")
    cur.execute("CREATE TABLE s13_t (id int PRIMARY KEY, note text) WITH (autovacuum_enabled = off)")
    cur.execute("INSERT INTO s13_t SELECT g, 'row ' || g FROM generate_series(1, 100) AS g")
    lsn0 = one(cur, "SELECT pg_current_wal_insert_lsn()")
    cur.execute("INSERT INTO s13_t VALUES (101, 'hello')")
    lsn1 = one(cur, "SELECT pg_current_wal_insert_lsn()")
    cur.execute("SELECT resource_manager || '/' || record_type FROM pg_get_wal_records_info(%s, %s)", (lsn0, lsn1))
    kinds = [r[0] for r in cur.fetchall()]
    check("1 行の INSERT とコミットで、Heap/INSERT → Btree/INSERT_LEAF → Transaction/COMMIT の順に WAL レコードが書かれる",
          [k for k in kinds if k in ("Heap/INSERT", "Btree/INSERT_LEAF", "Transaction/COMMIT")]
          == ["Heap/INSERT", "Btree/INSERT_LEAF", "Transaction/COMMIT"], str(kinds))
    rec, fpi, nbytes = wal_plan(explain(cur, "INSERT INTO s13_t VALUES (102, 'world')"))
    check("EXPLAIN (ANALYZE, WAL) の数にはコミットのレコードが入らない（ヒープとインデックスの 2 レコード）",
          rec == 2 and fpi == 0, f"records={rec} fpi={fpi} bytes={nbytes}")

    def lsns():
        cur.execute("""SELECT (SELECT lsn FROM page_header(get_raw_page('s13_t', 0))),
                              (SELECT lsn FROM page_header(pg_read_binary_file(pg_relation_filepath('s13_t'), 0, 8192))),
                              pg_current_wal_flush_lsn()""")
        return cur.fetchone()

    cur.execute("CHECKPOINT")
    b0, f0, _ = lsns()
    cur.execute("UPDATE s13_t SET note = 'updated' WHERE id = 1")
    b1, f1, fl1 = lsns()
    cur.execute("CHECKPOINT")
    b2, f2, _ = lsns()
    check("チェックポイント直後はメモリ上のページとファイル上のページの LSN が同じ", b0 == f0, f"{b0} {f0}")
    check("UPDATE 後: メモリ上のページは進むがファイル上のページは古いまま。WAL はそのページの LSN までディスクに書かれている",
          b1 > b0 and f1 == f0 and fl1 >= b1, f"buffer={b1} file={f1} flushed={fl1}")
    check("もう一度チェックポイントすると、ファイル上のページがメモリ上のページに追いつく", b2 == f2 == b1, f"{b2} {f2}")


def verify_commit_count(cur) -> None:
    n = 20000
    loop = "DO $$ BEGIN FOR i IN 1..%d LOOP INSERT INTO {t} SELECT * FROM orders WHERE id = i; %s END LOOP; END $$"
    runs = {"each": [], "once": [], "off": []}
    for _ in range(3):
        for kind in runs:
            fresh(cur, "s13_loop")
            if kind == "off":
                cur.execute("SET synchronous_commit = off")
            a = meter(cur)
            cur.execute((loop % (n, "" if kind == "once" else "COMMIT;")).format(t="s13_loop"))
            runs[kind].append(diff(a, meter(cur)))
            cur.execute("RESET synchronous_commit")
    each, once, off = runs["each"][-1], runs["once"][-1], runs["off"][-1]
    check(f"1 行ごとにコミット: {n} 回のコミットでこのセッションが WAL を約 {n} 回 fsync する",
          each["fsyncs"] >= 0.95 * n, str(each))
    check("最後に 1 回だけコミット: fsync は数回だけ", once["fsyncs"] <= 5, str(once))
    check("1 行ごとのコミットは WAL レコードが約 2 倍（INSERT と COMMIT が 1 つずつ）",
          abs(each["records"] - 2 * n) <= 20 and abs(once["records"] - n) <= 20, f"each={each['records']} once={once['records']}")
    check("synchronous_commit = off: コミットしてもこのセッションは fsync しない（WAL writer が後でまとめて書く）",
          off["fsyncs"] == 0 and abs(off["records"] - 2 * n) <= 20, str(off))
    m_each = statistics.median(r["ms"] for r in runs["each"])
    m_once = statistics.median(r["ms"] for r in runs["once"])
    m_off = statistics.median(r["ms"] for r in runs["off"])
    check("1 行ごとのコミットは、最後に 1 回だけのコミットより 5 倍以上遅い（実測は約 30 倍）",
          m_each > 5 * m_once, f"each={m_each:.0f}ms once={m_once:.0f}ms off={m_off:.0f}ms")
    check("synchronous_commit = off にすると 1 行ごとのコミットでも速くなる", m_off < m_each / 2,
          f"each={m_each:.0f}ms off={m_off:.0f}ms")

    # コミットが返った時点で、WAL がまだディスクに書かれていないことがある（off のとき）
    cur.execute("SET client_min_messages = warning")
    cur.execute("DROP TABLE IF EXISTS s13_one")
    cur.execute("RESET client_min_messages")
    cur.execute("CREATE TABLE s13_one (id int, note text) WITH (autovacuum_enabled = off)")
    cur.execute("SET synchronous_commit = off")
    seen = None
    for i in range(10):
        cur.execute("INSERT INTO s13_one VALUES (%s, 'off')", (i,))
        cur.execute("SELECT pg_current_wal_insert_lsn(), pg_wal_lsn_diff(pg_current_wal_insert_lsn(), pg_current_wal_flush_lsn())")
        lsn, gap = cur.fetchone()
        if gap > 0:
            seen = (lsn, gap)
            break
    cur.execute("RESET synchronous_commit")
    check("synchronous_commit = off: コミット直後に、まだ fsync されていない WAL（自分のコミットを含む）がある", seen is not None, str(seen))
    if seen:
        time.sleep(1)
        flushed = one(cur, "SELECT pg_current_wal_flush_lsn()")
        check("1 秒後には WAL writer がそこまで fsync している", flushed >= seen[0], f"{flushed} >= {seen[0]}")


def verify_copy(cur) -> None:
    buf = io.BytesIO()
    with cur.copy("COPY (SELECT * FROM orders WHERE id <= 100000 ORDER BY id) TO STDOUT") as cp:
        for chunk in cp:
            buf.write(chunk)
    fresh(cur, "s13_ins")
    fresh(cur, "s13_copy")
    a = meter(cur)
    cur.execute("INSERT INTO s13_ins SELECT * FROM orders WHERE id <= 100000 ORDER BY id")
    ins = diff(a, meter(cur))
    a = meter(cur)
    with cur.copy("COPY s13_copy FROM STDIN") as cp:
        cp.write(buf.getvalue())
    cpy = diff(a, meter(cur))
    check("10 万行: INSERT ... SELECT は 1 行 1 レコード、COPY はページごとにまとめるのでレコードが 1/10 未満",
          ins["records"] >= 100000 and cpy["records"] < ins["records"] / 10, f"insert={ins} copy={cpy}")
    check("COPY の WAL は INSERT ... SELECT の 7 割未満（実測は約 45%）", cpy["bytes"] < 0.7 * ins["bytes"],
          f"insert={ins['bytes']} copy={cpy['bytes']}")
    cur.execute("SELECT count(*), count(DISTINCT (ctid::text::point)[0]) FROM s13_copy")
    check("COPY でも行数・行の入ったページ数は同じ（10 万行・820 ページ）", cur.fetchone() == (100000, 820))


def verify_fpi(cur) -> None:
    fresh(cur, "s13_fpi", "fillfactor = 90, autovacuum_enabled = off")
    cur.execute("INSERT INTO s13_fpi SELECT * FROM orders WHERE id <= 100000 ORDER BY id")
    cur.execute("VACUUM s13_fpi")
    upd = "UPDATE s13_fpi SET status = status WHERE id % 100 = 0"
    cur.execute(upd)
    pages = one(cur, "SELECT pg_relation_size('s13_fpi') / 8192")

    def ckpt_stats():
        cur.execute("SELECT num_requested, buffers_written FROM pg_stat_checkpointer")
        return cur.fetchone()

    r0, w0 = ckpt_stats()
    cur.execute("CHECKPOINT")
    end = time.time() + 3
    r1, w1 = ckpt_stats()
    while r1 == r0 and time.time() < end:
        time.sleep(0.1)
        r1, w1 = ckpt_stats()
    check("CHECKPOINT で要求されたチェックポイントが 1 回増え、ダーティだった s13_fpi のページ以上を書き出す",
          r1 - r0 >= 1 and w1 - w0 >= pages, f"requested+{r1 - r0} buffers_written+{w1 - w0} pages={pages}")
    first = wal_plan(explain(cur, upd))
    second = wal_plan(explain(cur, upd))
    cur.execute("CHECKPOINT")
    third = wal_plan(explain(cur, upd))
    check("チェックポイント直後の UPDATE は、変更したページの数だけ FPI を書く（918 ページ）",
          first[1] == pages and third[1] == pages, f"pages={pages} first={first} third={third}")
    check("2 回目（チェックポイントなし）は FPI 0、WAL は 1/20 未満", second[1] == 0 and second[2] < first[2] / 20,
          f"first={first} second={second}")

    try:
        cur.execute("ALTER SYSTEM SET full_page_writes = off")
        cur.execute("SELECT pg_reload_conf()")
        # 設定の切り替えはチェックポインタが再読み込みしたときに反映されるので少し待つ。
        # 切り替え前に WAL を書いていた接続は、切り替え後の最初の 1 レコードだけ古い判断のまま FPI を付ける
        # （実測でページ 0 の 1 枚。新しい接続で実行した sql/session13/07_full_page_writes.sql では 0）
        time.sleep(1)
        ok = wait_setting(cur, "full_page_writes", "off")
        cur.execute("CHECKPOINT")
        nofpw = wal_plan(explain(cur, upd))
        check("full_page_writes = off: チェックポイント直後でも FPI がほぼ出ず（1 以下）、WAL は 1/20 未満",
              ok and nofpw[1] <= 1 and nofpw[2] < first[2] / 20, f"{nofpw}")
    finally:
        cur.execute("ALTER SYSTEM RESET full_page_writes")
        cur.execute("SELECT pg_reload_conf()")
    check("full_page_writes を元（on）に戻した", wait_setting(cur, "full_page_writes", "on"))

    # データチェックサム（PostgreSQL 18 の既定）では、チェックポイント後の最初のヒントビット設定でも FPI が出る
    fresh(cur, "s13_hint")
    cur.execute("INSERT INTO s13_hint SELECT * FROM orders WHERE id <= 100000 ORDER BY id")
    cur.execute("CHECKPOINT")
    r1 = explain(cur, "SELECT count(*) FROM s13_hint", buffers=True)
    r2 = explain(cur, "SELECT count(*) FROM s13_hint", buffers=True)
    check("data_checksums = on", one(cur, "SHOW data_checksums") == "on")
    check("チェックポイント直後の 1 回目の SELECT: 全 820 ページで dirtied、WAL に FPI 820（SELECT なのに WAL が出る）",
          r1["Plan"]["Shared Dirtied Blocks"] == 820 and wal_plan(r1)[1] == 820,
          f"dirtied={r1['Plan']['Shared Dirtied Blocks']} wal={wal_plan(r1)}")
    check("2 回目の SELECT: dirtied 0・WAL 0", r2["Plan"]["Shared Dirtied Blocks"] == 0 and wal_plan(r2) == (0, 0, 0),
          f"{wal_plan(r2)}")


def verify_bulk(cur) -> None:
    fresh(cur, "s13_first")
    cur.execute("ALTER TABLE s13_first ADD PRIMARY KEY (id)")
    cur.execute("CREATE INDEX s13_first_customer_id_idx ON s13_first (customer_id)")
    cur.execute("CREATE INDEX s13_first_ordered_at_idx ON s13_first (ordered_at)")
    cur.execute("CHECKPOINT")
    a = meter(cur)
    cur.execute("INSERT INTO s13_first SELECT * FROM orders ORDER BY id")
    first = diff(a, meter(cur))

    fresh(cur, "s13_after")
    cur.execute("CHECKPOINT")
    a = meter(cur)
    cur.execute("INSERT INTO s13_after SELECT * FROM orders ORDER BY id")
    plain = diff(a, meter(cur))
    cur.execute("ALTER TABLE s13_after ADD PRIMARY KEY (id)")
    cur.execute("CREATE INDEX s13_after_customer_id_idx ON s13_after (customer_id)")
    cur.execute("CREATE INDEX s13_after_ordered_at_idx ON s13_after (ordered_at)")
    after = diff(a, meter(cur))
    check("100 万行: インデックスを先に作ると、後から作るより WAL が 1.5 倍以上（実測 295MB と 136MB）",
          first["bytes"] > 1.5 * after["bytes"], f"first={first['bytes']} after={after['bytes']}")
    check("インデックスを後から作る方が速い（実測で約 3.6 倍）", first["ms"] > after["ms"],
          f"first={first['ms']:.0f}ms after={after['ms']:.0f}ms")
    check("後から作るインデックスはページの写し（FPI）として WAL に書かれる", after["fpi"] - plain["fpi"] > 5000,
          f"fpi={after['fpi'] - plain['fpi']}")

    fresh(cur, "s13_unlogged", unlogged=True)
    cur.execute("CHECKPOINT")
    a = meter(cur)
    cur.execute("INSERT INTO s13_unlogged SELECT * FROM orders ORDER BY id")
    unl = diff(a, meter(cur))
    check("UNLOGGED テーブルへの 100 万行は WAL をほとんど書かない（1MB 未満。普通の表は約 91MB）",
          unl["bytes"] < 1_000_000 and plain["bytes"] > 50_000_000, f"unlogged={unl['bytes']} logged={plain['bytes']}")
    cur.execute("""SELECT relpersistence, (pg_stat_file(pg_relation_filepath('s13_unlogged') || '_init')).size
                   FROM pg_class WHERE relname = 's13_unlogged'""")
    check("UNLOGGED テーブルは relpersistence = 'u' で、空の初期化フォーク（_init）を持つ", cur.fetchone() == ("u", 0))
    a = meter(cur)
    cur.execute("ALTER TABLE s13_unlogged SET LOGGED")
    setl = diff(a, meter(cur))
    check("SET LOGGED にするとテーブル全体を WAL に書く（50MB 超）",
          setl["bytes"] > 50_000_000 and one(cur, "SELECT relpersistence FROM pg_class WHERE relname = 's13_unlogged'") == "p",
          f"{setl['bytes']}")


def verify_max_wal_size(cur) -> None:
    def load() -> tuple[dict, int]:
        fresh(cur, "s13_first")
        cur.execute("ALTER TABLE s13_first ADD PRIMARY KEY (id)")
        cur.execute("CREATE INDEX s13_first_customer_id_idx ON s13_first (customer_id)")
        cur.execute("CREATE INDEX s13_first_ordered_at_idx ON s13_first (ordered_at)")
        cur.execute("CHECKPOINT")
        time.sleep(0.3)
        req0 = one(cur, "SELECT num_requested FROM pg_stat_checkpointer")
        a = meter(cur)
        cur.execute("INSERT INTO s13_first SELECT * FROM orders WHERE id <= 300000 ORDER BY id")
        d = diff(a, meter(cur))
        time.sleep(1)
        return d, one(cur, "SELECT num_requested FROM pg_stat_checkpointer") - req0

    base, base_ck = load()
    try:
        cur.execute("ALTER SYSTEM SET max_wal_size = '32MB'")
        cur.execute("SELECT pg_reload_conf()")
        ok = wait_setting(cur, "max_wal_size", "32MB")
        small, small_ck = load()
    finally:
        cur.execute("ALTER SYSTEM RESET max_wal_size")
        cur.execute("SELECT pg_reload_conf()")
    check("max_wal_size = 1GB（既定）: 30 万行の投入中に WAL の量によるチェックポイントは起きない", base_ck == 0, f"{base_ck}")
    check("max_wal_size = 32MB: 投入中にチェックポイントが何度も起き（3 回以上）、FPI が大幅に増えて WAL が膨らむ",
          ok and small_ck >= 3 and small["fpi"] > 1000 and small["fpi"] > 100 * (base["fpi"] + 1) and small["bytes"] > base["bytes"],
          f"ckpt={small_ck} fpi {base['fpi']}->{small['fpi']} bytes {base['bytes']}->{small['bytes']}")
    check("max_wal_size を元（1GB）に戻した", wait_setting(cur, "max_wal_size", "1GB"))


def verify_mysql() -> None:
    m = mysql_connect()
    cur = m.cursor()
    cur.execute("SHOW VARIABLES WHERE Variable_name IN ('innodb_flush_log_at_trx_commit', 'innodb_doublewrite')")
    v = dict(cur.fetchall())
    check("MySQL: innodb_flush_log_at_trx_commit = 1（コミットごとに REDO を fsync）・二重書き込みバッファ ON",
          v.get("innodb_flush_log_at_trx_commit") == "1" and v.get("innodb_doublewrite") == "ON", str(v))
    cur.execute("DROP TABLE IF EXISTS s13_my")
    cur.execute("CREATE TABLE s13_my LIKE orders")
    cur.execute("DROP PROCEDURE IF EXISTS s13_insert_rows")
    cur.execute("CREATE PROCEDURE s13_insert_rows(n INT) BEGIN DECLARE i INT DEFAULT 1; "
                "WHILE i <= n DO INSERT INTO s13_my SELECT * FROM orders WHERE id = i; SET i = i + 1; END WHILE; END")

    def fsyncs() -> int:
        cur.execute("SELECT VARIABLE_VALUE FROM performance_schema.global_status WHERE VARIABLE_NAME = 'Innodb_os_log_fsyncs'")
        return int(cur.fetchone()[0])

    try:
        n = 2000
        f0 = fsyncs()
        cur.execute("CALL s13_insert_rows(%s)", (n,))
        auto = fsyncs() - f0
        cur.execute("TRUNCATE s13_my")
        f0 = fsyncs()
        cur.execute("START TRANSACTION")
        cur.execute("CALL s13_insert_rows(%s)", (n,))
        cur.execute("COMMIT")
        tx = fsyncs() - f0
        check(f"MySQL: 自動コミットの {n} 行は REDO の fsync が約 {n} 回、1 トランザクションでは数回",
              auto >= 0.9 * n and tx < 50, f"auto={auto} tx={tx}")
    finally:
        cur.execute("DROP PROCEDURE IF EXISTS s13_insert_rows")
        cur.execute("DROP TABLE IF EXISTS s13_my")
        m.close()


def main() -> None:
    c = pg_connect()
    c.prepare_threshold = None
    cur = c.cursor()
    cur.execute("SET track_wal_io_timing = on")
    verify_wal_records(cur)
    verify_commit_count(cur)
    verify_copy(cur)
    verify_fpi(cur)
    verify_bulk(cur)
    verify_max_wal_size(cur)
    c.close()
    verify_mysql()
    finish("S13 書き込みの仕組み — WAL と耐久性")


if __name__ == "__main__":
    main()

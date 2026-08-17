#!/usr/bin/env python3
"""表を構造化データとして別に持ち、数値条件で引く（sqlite3・標準ライブラリのみ）。

テキスト検索は「語が一致するか」しか判定できない。「30,000円以上」のような比較は
検索の仕事ではなくデータ型の仕事なので、表だけを別のストアに持つ。

    python src/session15/table_store.py
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from ragkit.corpus import load_docs  # noqa: E402
from ragkit.models import Doc  # noqa: E402
from table_tools import COLUMN_TYPES, measure, parse_tables  # noqa: E402

SCHEMA = """
CREATE TABLE cells (
    doc_id     TEXT NOT NULL,
    doc_title  TEXT NOT NULL,
    caption    TEXT NOT NULL,
    table_no   INTEGER NOT NULL,
    row_no     INTEGER NOT NULL,
    row_key    TEXT NOT NULL,
    col_name   TEXT NOT NULL,
    value_text TEXT NOT NULL,
    col_type   TEXT,
    bound      TEXT,
    value_num  REAL,
    unit       TEXT,
    visibility TEXT NOT NULL,
    category   TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX idx_cells_col ON cells(col_name, value_num);
"""

# 比較演算子はホワイトリストで受ける（SQL 文字列に外から来た記号を混ぜない）
OPS = {">=", ">", "<=", "<", "=", "!="}


def build_db(docs: list[Doc], path: str = ":memory:") -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    rows = []
    for doc in docs:
        for table_no, table in enumerate(parse_tables(doc), start=1):
            key_index = table.key_index()
            for row_no, row in enumerate(table.rows, start=1):
                for col, value in zip(table.columns, row):
                    col_type = COLUMN_TYPES.get(col)
                    m = measure(col_type or "", value)
                    rows.append((
                        doc.doc_id, doc.title, table.caption, table_no, row_no,
                        row[key_index], col, value, col_type,
                        m.bound if m.value is not None else None,
                        m.value, m.unit or None,
                        doc.visibility, doc.category, doc.updated_at,
                    ))
    conn.executemany(
        "INSERT INTO cells VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows
    )
    conn.commit()
    return conn


def find_rows(
    conn: sqlite3.Connection,
    col_name: str,
    op: str,
    value: float,
    *,
    bounds: tuple[str, ...] = ("定額",),
    visibility: tuple[str, ...] = ("all",),
) -> list[sqlite3.Row]:
    """数値条件に合う行を返す。値はすべてプレースホルダで渡す。"""
    if op not in OPS:
        raise ValueError(f"許可していない演算子です: {op}")
    sql = (
        "SELECT doc_id, doc_title, row_key, value_text, value_num, unit, bound "
        "FROM cells WHERE col_name = ? AND value_num IS NOT NULL "
        f"AND value_num {op} ? "
        f"AND bound IN ({','.join('?' * len(bounds))}) "
        f"AND visibility IN ({','.join('?' * len(visibility))}) "
        "ORDER BY value_num DESC, doc_id, row_no"
    )
    return conn.execute(sql, (col_name, value, *bounds, *visibility)).fetchall()


def sum_of(conn: sqlite3.Connection, col_name: str,
           bounds: tuple[str, ...] = ("定額",)) -> float:
    sql = (
        "SELECT COALESCE(SUM(value_num), 0) AS s FROM cells "
        "WHERE col_name = ? AND value_num IS NOT NULL "
        f"AND bound IN ({','.join('?' * len(bounds))})"
    )
    return float(conn.execute(sql, (col_name, *bounds)).fetchone()["s"])


def stats(conn: sqlite3.Connection) -> dict:
    one = conn.execute(
        "SELECT COUNT(*) AS cells, "
        "SUM(col_type IS NOT NULL) AS typed, "
        "SUM(value_num IS NOT NULL) AS numeric, "
        "SUM(bound = '上限') AS bounded FROM cells"
    ).fetchone()
    return {k: int(one[k] or 0) for k in ("cells", "typed", "numeric", "bounded")}


QUESTIONS = [
    ("月額が30,000円以上の手当は", "月額", ">=", 30000.0, ("定額",)),
    ("上限額も含めて30,000円以上の手当は", "月額", ">=", 30000.0, ("定額", "上限")),
    ("メモリが32GB以上の貸与PCは", "メモリ", ">=", 32.0, ("定額",)),
    ("定員が10名以上の会議室は", "定員", ">=", 10.0, ("定額",)),
    ("保管期間が3年（36か月）以上の文書は", "保管期間", ">=", 36.0, ("定額",)),
]


def main() -> None:
    conn = build_db(load_docs())
    s = stats(conn)
    print(f"セル: {s['cells']} / 型を宣言した列のセル: {s['typed']} "
          f"/ 数値にできたセル: {s['numeric']} / うち上限型: {s['bounded']}")

    for label, col, op, value, bounds in QUESTIONS:
        hits = find_rows(conn, col, op, value, bounds=bounds)
        print(f"\n--- {label} ---")
        for r in hits:
            print(f"{r['doc_id']} {r['row_key']}: {r['value_text']} "
                  f"（{r['value_num']:.0f}{r['unit']}・{r['bound']}）")
        print(f"該当 {len(hits)} 件")

    print(f"\n定額の手当の合計: {sum_of(conn, '月額'):.0f} 円")
    print(f"上限額も足した場合: {sum_of(conn, '月額', ('定額', '上限')):.0f} 円")


if __name__ == "__main__":
    main()

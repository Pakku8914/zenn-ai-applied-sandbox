#!/usr/bin/env python3
"""表がチャンク分割でどう壊れるかを、実コーパスで数える。

判定は3つ。
  そろっている（intact）: 1つのチャンクにヘッダ行と全データ行が入っている
  孤児行（orphan）      : ヘッダ行と同居しないデータ行
  行の分断（lost）      : どのチャンクにも完全な形で現れないデータ行

    python src/session15/table_break.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from ragkit.chunk import chunk_fixed, chunk_heading, chunk_sentence  # noqa: E402
from ragkit.corpus import load_docs  # noqa: E402
from ragkit.models import Doc  # noqa: E402
from table_tools import Table, parse_tables  # noqa: E402

METHODS = [
    ("fixed(400/80)", lambda d: chunk_fixed(d, 400, 80)),
    ("fixed(200/0)", lambda d: chunk_fixed(d, 200, 0)),
    ("sentence(400)", lambda d: chunk_sentence(d, 400)),
    ("heading(600)", lambda d: chunk_heading(d, 600)),
]


def inspect_table(table: Table, texts: list[str]) -> dict:
    """1つの表について、チャンク列の中での壊れ方を調べる。"""
    header = table.header_line()
    rows = [table.row_line(r) for r in table.rows]
    intact = any(header in t and all(r in t for r in rows) for t in texts)
    with_header = sum(1 for r in rows if any(header in t and r in t for t in texts))
    present = sum(1 for r in rows if any(r in t for t in texts))
    return {
        "intact": intact,
        "rows": len(rows),
        "orphan": present - with_header,
        "lost": len(rows) - present,
    }


def report(docs: list[Doc]) -> list[dict]:
    out: list[dict] = []
    for label, chunker in METHODS:
        total = dict(label=label, tables=0, intact=0, rows=0, orphan=0, lost=0)
        for doc in docs:
            tables = parse_tables(doc)
            if not tables:
                continue
            texts = [c.text for c in chunker(doc)]
            for table in tables:
                r = inspect_table(table, texts)
                total["tables"] += 1
                total["intact"] += int(r["intact"])
                total["rows"] += r["rows"]
                total["orphan"] += r["orphan"]
                total["lost"] += r["lost"]
        out.append(total)
    return out


def show_orphan_example(doc: Doc) -> bool:
    """ヘッダから切り離された行だけを持つチャンクを1つ表示する。"""
    for table in parse_tables(doc):
        header = table.header_line()
        rows = [table.row_line(r) for r in table.rows]
        for chunk in chunk_fixed(doc, 400, 80):
            hit = [r for r in rows if r in chunk.text]
            if hit and header not in chunk.text:
                print(f"\n--- 孤児行の実例: {chunk.chunk_id}（{doc.title}）---")
                print(chunk.text[:180].replace("\n", " / "))
                print(f"（このチャンクには {len(hit)} 行が入っているが、列名が入っていない）")
                return True
    return False


def main() -> None:
    docs = load_docs()
    with_table = [d for d in docs if parse_tables(d)]
    print(f"表を含む文書: {len(with_table)} 件 / 全 {len(docs)} 件")
    print(f"表の数: {sum(len(parse_tables(d)) for d in with_table)} 個 "
          f"/ データ行: {sum(len(t.rows) for d in with_table for t in parse_tables(d))} 行")

    print("\n| 方式 | 表 | そろっている | 孤児行 | 行の分断 |")
    print("| :--- | --: | --: | --: | --: |")
    for r in report(docs):
        print(f"| {r['label']} | {r['tables']} | {r['intact']} | {r['orphan']} | {r['lost']} |")

    for doc in with_table:
        if show_orphan_example(doc):
            break


if __name__ == "__main__":
    main()

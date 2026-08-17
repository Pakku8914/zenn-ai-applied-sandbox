#!/usr/bin/env python3
"""混在文書を型別に分岐させて取り込むパイプライン。

1つの文書は「本文」「表」「コード」の3種類のブロックでできている。すべてを同じ
チャンカーに通すのではなく、型を判定してから別々の道具に渡す。

    python src/session15/pipeline.py
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from ragkit.chunk import chunk_fixed  # noqa: E402
from ragkit.corpus import load_docs  # noqa: E402
from ragkit.models import Chunk, Doc  # noqa: E402
from code_search import CodeUnit, code_units  # noqa: E402
from table_tools import _HEADING, _ROW, _SEP, parse_tables, row_chunks  # noqa: E402

_FENCE = re.compile(r"^\s*```")

# 質問からどの経路に流すかを決めるパターン（順番に評価する）
_NUM_COND = re.compile(r"\d[\d,]*\s*(?:万円|円|GB|名|時間|年|か月|日)\s*(?:以上|以下|未満|超|以内)")
_AGGREGATE = re.compile(r"(合計|何件|平均|一番|最も)")
_IDENTIFIER = re.compile(r"[A-Za-z][A-Za-z0-9]*_[A-Za-z0-9_]+|[a-z]+[A-Z][a-z]+")
_CELL = re.compile(r"(いくら|何GB|定員|メモリ|月額|保管期間|貸出期間)")


@dataclass(frozen=True)
class Block:
    """文書を型で切り分けたときの1かたまり。"""

    kind: str  # text / table / code
    caption: str
    text: str


@dataclass(frozen=True)
class Ingested:
    """1文書を型別に取り込んだ結果。"""

    doc_id: str
    text_chunks: list[Chunk]
    row_chunks: list[Chunk]
    code_units: list[CodeUnit]
    blocks: list[Block]


def split_blocks(doc: Doc) -> list[Block]:
    """本文・表・コードにブロック分割する。"""
    lines = doc.body.split("\n")
    blocks: list[Block] = []
    buf: list[str] = []
    caption = ""
    i = 0

    def flush() -> None:
        if buf and "".join(buf).strip():
            blocks.append(Block("text", caption, "\n".join(buf).strip()))
        buf.clear()

    while i < len(lines):
        line = lines[i]
        if _FENCE.match(line):
            flush()
            body = [line]
            i += 1
            while i < len(lines):
                body.append(lines[i])
                if _FENCE.match(lines[i]):
                    i += 1
                    break
                i += 1
            blocks.append(Block("code", caption, "\n".join(body)))
            continue
        if (_ROW.match(line) and not _SEP.match(line)
                and i + 1 < len(lines) and _SEP.match(lines[i + 1])):
            flush()
            body = [line]
            i += 1
            while i < len(lines) and _ROW.match(lines[i]):
                body.append(lines[i])
                i += 1
            blocks.append(Block("table", caption, "\n".join(body)))
            continue
        m = _HEADING.match(line)
        if m:
            caption = m.group(1).strip()
        buf.append(line)
        i += 1
    flush()
    return blocks


def false_headings(doc: Doc) -> list[str]:
    """フェンスの内側にある「見出しに見える行」（ragkit.chunk_heading が誤検出する行）。"""
    out: list[str] = []
    for block in split_blocks(doc):
        if block.kind != "code":
            continue
        out.extend(ln for ln in block.text.split("\n")
                   if _HEADING.match(ln) and not _FENCE.match(ln))
    return out


def mask_fences(body: str) -> str:
    """フェンスの内側を伏せ字にする。見出しを探す前に通せば誤検出が消える。"""
    out: list[str] = []
    in_fence = False
    for line in body.split("\n"):
        if _FENCE.match(line):
            in_fence = not in_fence
            out.append(line)
            continue
        out.append("<code>" if in_fence else line)
    return "\n".join(out)


def text_only(doc: Doc) -> Doc:
    """表とコードを抜いた本文だけの文書を作る（テキスト索引に渡す用）。"""
    body = "\n\n".join(b.text for b in split_blocks(doc) if b.kind == "text")
    return replace(doc, body=body)


def ingest(doc: Doc) -> Ingested:
    """型別に取り込む。テキストはチャンク、表は行、コードは関数単位。"""
    return Ingested(
        doc_id=doc.doc_id,
        text_chunks=chunk_fixed(text_only(doc), 400, 80),
        row_chunks=row_chunks(doc),
        code_units=code_units(doc),
        blocks=split_blocks(doc),
    )


def route(query: str) -> str:
    """質問をどの経路に流すかを決める（上から順に評価する）。"""
    if _NUM_COND.search(query) or _AGGREGATE.search(query):
        return "structured"
    if _IDENTIFIER.search(query):
        return "code"
    if _CELL.search(query):
        return "row"
    return "text"


def inventory(docs: list[Doc]) -> dict:
    tables = [t for d in docs for t in parse_tables(d)]
    units = [u for d in docs for u in code_units(d)]
    return {
        "docs": len(docs),
        "docs_with_table": len({t.doc_id for t in tables}),
        "docs_with_code": len({u.doc_id for u in units}),
        "tables": len(tables),
        "table_rows": sum(len(t.rows) for t in tables),
        "code_units": len(units),
        "code_lines": sum(len(u.text.splitlines()) for u in units),
        "false_headings": sum(len(false_headings(d)) for d in docs),
        "images": sum(d.body.count("![") for d in docs),
    }


SAMPLE_QUERIES = [
    "月額が3万円以上の手当は",
    "セキュリティの文書は何件ありますか",
    "find_asset は何をする関数ですか",
    "役職手当の月額はいくらですか",
    "有給休暇の申請期限を教えてください",
]


def main() -> None:
    docs = load_docs()
    inv = inventory(docs)
    print("--- 資産の棚卸し ---")
    for k, v in inv.items():
        print(f"{k}: {v}")

    kinds: dict[str, int] = {}
    for doc in docs:
        for b in split_blocks(doc):
            kinds[b.kind] = kinds.get(b.kind, 0) + 1
    print(f"\nブロック数: {kinds}")

    ing = [ingest(d) for d in docs]
    print(f"テキストチャンク: {sum(len(i.text_chunks) for i in ing)} / "
          f"行チャンク: {sum(len(i.row_chunks) for i in ing)} / "
          f"コード単位: {sum(len(i.code_units) for i in ing)}")

    print("\n--- 質問のルーティング ---")
    for q in SAMPLE_QUERIES:
        print(f"{route(q):<11} {q}")


if __name__ == "__main__":
    main()

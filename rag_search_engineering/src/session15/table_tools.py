"""表を検索できる形に変えるための道具（セッション15）。

コーパスの表は Markdown の表として本文に埋まっている。テキストのまま索引に載せると
「行」と「見出し」が離れ、数値の比較もできない。ここでは次の3つを用意する。

  parse_tables(doc)          Markdown の表を（直前の見出しを添えて）取り出す
  row_sentence(table, row)   1行を1文にする（行文章化）
  row_chunks(doc)            行文章化した仮想チャンクを作る（検索単位を行にする）
  measure(col_type, text)    列に宣言した型に従って数値と単位を取り出す
  naive_number(text)         型を宣言せずに数値を拾う（アンチパターン。比較用）

ragkit は変更しない。ここに置いたものはセッション15の中だけで完結する。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ragkit.models import Chunk, Doc

# ragkit.chunk と同じ見出し判定を使う（挙動をそろえるため意図的に同じ正規表現にする）
_HEADING = re.compile(r"^#{1,4}\s*(.+)$")
_ROW = re.compile(r"^\s*\|(.+)\|\s*$")
_SEP = re.compile(r"^\s*\|[\s:|-]+\|\s*$")
_FENCE = re.compile(r"^\s*```")

# 行文章化のときに読み飛ばす列（連番だけの列は文にしても意味がない）
SKIP_COLUMNS = ("#",)
# 空セルとして扱う表記
EMPTY_CELLS = ("", "—", "-", "ー", "－")


@dataclass(frozen=True)
class Table:
    """文書から取り出した1つの表。"""

    doc_id: str
    doc_title: str
    caption: str  # 直前の見出し（例「一覧」「確認項目」）
    columns: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]
    meta: dict = field(default_factory=dict)

    def header_line(self) -> str:
        """原文のヘッダ行を復元する（チャンクに残っているかを調べるために使う）。"""
        return "| " + " | ".join(self.columns) + " |"

    def row_line(self, row: tuple[str, ...]) -> str:
        """原文のデータ行を復元する。"""
        return "| " + " | ".join(row) + " |"

    def key_index(self) -> int:
        """行を識別する列（連番列を除いた最初の列）の位置。"""
        for i, c in enumerate(self.columns):
            if c not in SKIP_COLUMNS:
                return i
        return 0


def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def parse_tables(doc: Doc) -> list[Table]:
    """文書から Markdown の表をすべて取り出す。

    「ヘッダ行 → 区切り行 → データ行」の並びだけを表とみなす。コードブロックの中に
    ある `|` を表と誤認しないよう、フェンス（```）の内側は無視する。
    """
    lines = doc.body.split("\n")
    tables: list[Table] = []
    caption = ""
    in_fence = False
    i = 0
    while i < len(lines):
        line = lines[i]
        if _FENCE.match(line):
            in_fence = not in_fence
            i += 1
            continue
        if in_fence:
            i += 1
            continue

        heading = _HEADING.match(line)
        if heading:
            caption = heading.group(1).strip()
            i += 1
            continue

        is_header = (
            _ROW.match(line)
            and not _SEP.match(line)
            and i + 1 < len(lines)
            and _SEP.match(lines[i + 1])
        )
        if not is_header:
            i += 1
            continue

        columns = tuple(_cells(line))
        rows: list[tuple[str, ...]] = []
        j = i + 2
        while j < len(lines) and _ROW.match(lines[j]) and not _SEP.match(lines[j]):
            cells = _cells(lines[j])
            if len(cells) == len(columns):  # 列数が合わない行は取り込まない
                rows.append(tuple(cells))
            j += 1
        if rows:
            tables.append(
                Table(
                    doc_id=doc.doc_id,
                    doc_title=doc.title,
                    caption=caption,
                    columns=columns,
                    rows=tuple(rows),
                    meta={
                        "title": doc.title,
                        "category": doc.category,
                        "updated_at": doc.updated_at,
                        "visibility": doc.visibility,  # 権限は必ず引き継ぐ（セッション13）
                        "dept": doc.dept,
                        "source_type": doc.source_type,
                    },
                )
            )
        i = j
    return tables


def row_sentence(table: Table, row: tuple[str, ...]) -> str:
    """表の1行を1文にする（行文章化）。

    「どの文書のどの表の行か」を文の中に入れておくと、行だけを読んでも主題が分かる。
    セッション4で見出し分割が各節に文書タイトルを前置していたのと同じ考え方。
    """
    parts = [
        f"{col}は{value}"
        for col, value in zip(table.columns, row)
        if col not in SKIP_COLUMNS and value not in EMPTY_CELLS
    ]
    return f"{table.doc_title}／{table.caption}：{'、'.join(parts)}。"


def row_chunks(doc: Doc) -> list[Chunk]:
    """文書の表を行単位の仮想チャンクにする。

    chunk_id は本文チャンク（`DOC-0001#001`）と衝突させないため `#R01` の別系列にする。
    検索単位が違うものに同じ ID を振ると、あとで結果を畳み込むときに事故になる。
    """
    out: list[Chunk] = []
    n = 0
    for table_no, table in enumerate(parse_tables(doc), start=1):
        key_index = table.key_index()
        for row_no, row in enumerate(table.rows, start=1):
            n += 1
            out.append(
                Chunk(
                    chunk_id=f"{doc.doc_id}#R{n:02d}",
                    doc_id=doc.doc_id,
                    text=row_sentence(table, row),
                    ordinal=n,
                    meta={
                        **table.meta,
                        "method": "row",
                        "caption": table.caption,
                        "table_no": table_no,
                        "row_no": row_no,
                        "row_key": row[key_index],
                    },
                )
            )
    return out


# ---------------------------------------------------------------------------
# 列に型を宣言してから数値を取り出す
# ---------------------------------------------------------------------------

# 列名 -> 型。ここに無い列は数値として扱わない（宣言しない列は数値化しない）
COLUMN_TYPES: dict[str, str] = {
    "月額": "yen",
    "月額利用料": "yen",
    "メモリ": "gb",
    "定員": "people",
    "連続利用の上限": "hour",
    "保管期間": "months",
    "貸出期間": "months",
}

# 型ごとに許す単位と、正規化するときの倍率
TYPE_UNITS: dict[str, dict[str, float]] = {
    "yen": {"円": 1.0},
    "gb": {"GB": 1.0},
    "people": {"名": 1.0},
    "hour": {"時間": 1.0},
    "months": {"年": 12.0, "か月": 1.0},
}
TYPE_UNIT_NAME = {"yen": "円", "gb": "GB", "people": "名", "hour": "時間", "months": "か月"}

# 「その値そのもの」ではなく「上限」を表す語。含まれていたら bound を分ける
BOUND_WORDS = ("上限", "最長")

_NUM = re.compile(r"(\d[\d,]*)\s*(円|GB|名|時間|年|か月|営業日|日|分|件)?")
_ANY_NUM = re.compile(r"(\d[\d,]*)")


@dataclass(frozen=True)
class Measure:
    """セルから取り出した量。

    bound: 定額（その値そのもの）／上限（それ以下という意味）／不明（数値にできない）
    value: 型の基準単位に正規化した値（months なら「か月」、yen なら「円」）
    """

    bound: str
    value: float | None
    unit: str


def measure(col_type: str, text: str) -> Measure:
    """列の型に従ってセルを数値にする。型と単位が合わなければ捨てる。"""
    if col_type not in TYPE_UNITS:
        return Measure("不明", None, "")
    m = _NUM.search(text)
    if not m:
        return Measure("不明", None, "")
    scale = TYPE_UNITS[col_type].get(m.group(2) or "")
    if scale is None:
        return Measure("不明", None, "")  # 単位が列の型と合わない → 人手に回す
    value = int(m.group(1).replace(",", "")) * scale
    bound = "上限" if any(w in text for w in BOUND_WORDS) else "定額"
    return Measure(bound, value, TYPE_UNIT_NAME[col_type])


def naive_number(text: str) -> int | None:
    """型を宣言せず、最初に見つけた数字を値とみなす（アンチパターン）。"""
    m = _ANY_NUM.search(text)
    return int(m.group(1).replace(",", "")) if m else None

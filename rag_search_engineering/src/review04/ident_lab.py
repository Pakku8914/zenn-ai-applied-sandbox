#!/usr/bin/env python3
"""横断復習04：索引側とクエリ側を「同じ規則」で分割する（セッション15 × セッション5）。

コード検索が成立する条件は1つ。**索引側とクエリ側が同じ分割規則を通っている**ことである。
片側だけ分割しても `build_incident_report` と `buildIncidentReport` は結びつかない。

コード片はこのファイル内に置いている（コーパスは読み込まない）。トークナイザの挙動だけは
仮定せず、ragkit の実装に1行流して出力を見る。

実行:  docker compose exec app python src/review04/ident_lab.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ragkit.tokenize_ja import tokenize  # noqa: E402

_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
# 大文字略語・キャメルケースの語・小文字語をそれぞれ1語として拾う
_PART = re.compile(r"[A-Z]+(?![a-z])|[A-Z][a-z0-9]*|[a-z0-9]+")

KEYWORDS = frozenset({
    "def", "class", "return", "for", "if", "else", "in", "is", "not", "and", "or",
    "none", "true", "false", "str", "int", "float", "bool", "dict", "list", "self",
    "import", "from", "as", "with", "try", "except", "raise", "pass", "lambda",
})

# 検索単位（関数1つ）。みなと商事のコーパスに入っている社内スクリプトと同じ形にしている
UNITS: dict[str, str] = {
    "build_incident_report": (
        'def build_incident_report(ticket_id: str) -> dict:\n'
        '    ticket = load_ticket(ticket_id)\n'
        '    return {"id": ticket_id, "summary": ticket["title"]}\n'
    ),
    "find_asset": (
        'def find_asset(asset_tag: str) -> dict | None:\n'
        '    for row in load_asset_ledger():\n'
        '        if row["asset_tag"] == asset_tag:\n'
        '            return row\n'
        '    return None\n'
    ),
}


def split_identifier(name: str) -> list[str]:
    """`find_asset` -> [find, asset] / `buildIncidentReport` -> [build, incident, report]。

    小文字化してから呼ぶとキャメルケースの境界が消える。分割は**元の大小文字のまま**行う。
    """
    out: list[str] = []
    for chunk in re.split(r"_+", name):
        out.extend(m.group(0).lower() for m in _PART.finditer(chunk))
    return [p for p in out if p]


def identifiers(text: str) -> list[str]:
    """識別子そのもの（大小文字を保つ・1文字と予約語は捨てる）。"""
    return [m.group(0) for m in _IDENT.finditer(text)
            if len(m.group(0)) >= 2 and m.group(0).lower() not in KEYWORDS]


def index_terms(text: str, split: bool = True) -> tuple[set[str], set[str]]:
    """索引に載せる語を返す。(完全一致用の識別子, 索引語の全体)。"""
    names = identifiers(text)
    full = {n.lower() for n in names}
    toks = set(full)
    if split:
        for n in names:
            parts = split_identifier(n)
            if len(parts) > 1:
                toks.update(parts)
    return full, toks


def query_terms(query: str, split: bool = True) -> tuple[set[str], set[str]]:
    """クエリ側も**同じ分割規則**を通す。ここが索引側とずれた瞬間に検索が壊れる。"""
    names = identifiers(query)
    exact = {n.lower() for n in names}
    parts: set[str] = set()
    if split:
        for n in names:
            parts.update(split_identifier(n))
    return exact, parts


def search(query: str, index_split: bool = True, query_split: bool = True,
           exact_weight: float = 3.0, partial_weight: float = 1.0
           ) -> list[tuple[float, str]]:
    """完全一致（識別子そのもの）を重く、部分語を軽く採点する。"""
    q_exact, q_parts = query_terms(query, split=query_split)
    scored: list[tuple[float, str]] = []
    for name, text in UNITS.items():
        full, toks = index_terms(text, split=index_split)
        score = exact_weight * len(q_exact & full) + partial_weight * len(q_parts & toks)
        if score > 0:
            scored.append((score, name))
    scored.sort(key=lambda x: (-x[0], x[1]))
    return scored


def literal_search(text: str) -> list[str]:
    """記号を含む文字列は索引を通さず逐次一致で探す（grep 相当の最後の手段）。"""
    return sorted(name for name, body in UNITS.items() if text in body)


# 型別パイプライン（セッション15）。同じ索引に全部を流し込まないための対応表
TYPE_PIPELINE: dict[str, tuple[str, str]] = {
    "本文": ("文境界・見出しで分割して BM25 と密ベクトルへ", "既定の経路"),
    "表": ("行文章化して本文と同じ索引へ＋原表を型付きで構造化保持", "数値条件は SQL で解く"),
    "コード": ("識別子＋部分語で索引化し、記号は逐次一致", "索引側とクエリ側で同じ分割規則"),
    "画像": ("キャプションと近傍テキストを索引化", "OCR・マルチモーダルは必要が出てから"),
}


def main() -> None:
    print("=== 1. 分割規則（索引側とクエリ側の両方に同じ関数を通す）===")
    for name in ("find_asset", "buildIncidentReport", "build_incident_report",
                 "buildincidentreport", "MFA_reset", "HTTPServerError"):
        print(f"  {name:<22} -> {split_identifier(name)}")

    print("\n=== 2. 片側だけ分割すると成立しない（クエリ: buildIncidentReport）===")
    for idx in (True, False):
        for qry in (True, False):
            hits = search("buildIncidentReport", index_split=idx, query_split=qry)
            got = ", ".join(f"{n}({s:.0f})" for s, n in hits) or "（0件）"
            print(f"  索引側の分割={str(idx):<5} クエリ側の分割={str(qry):<5} -> {got}")

    print("\n=== 3. 3段構え（完全一致 / 部分語 / 逐次一致）===")
    for q in ("find_asset", "asset", "report"):
        hits = search(q)
        print(f"  クエリ「{q}」-> " + (", ".join(f"{n}({s:.0f})" for s, n in hits) or "（0件）"))
    print(f"  逐次一致「==」-> {literal_search('==')}")
    print(f"  トークン検索「==」-> {search('==') or '（0件）'}")

    print("\n=== 4. トークナイザは仮定せず1行流して確かめる ===")
    print(f"  tokenize('==', 'morph')         -> {tokenize('==', 'morph')}")
    print(f"  tokenize('find_asset', 'morph') -> {tokenize('find_asset', 'morph')}")

    print("\n=== 5. 型別パイプライン ===")
    for kind, (how, note) in TYPE_PIPELINE.items():
        print(f"  {kind:<4} {how}（{note}）")


if __name__ == "__main__":
    main()

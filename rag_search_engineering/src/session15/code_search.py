#!/usr/bin/env python3
"""コードを検索できる形にする（識別子・記号・トークナイズ）。

自然文のトークナイザは、コードに対して2つの壊れ方をする。
  1. `find_asset` のような識別子を「1つの語」として索引に載せられない
  2. `==` `->` のような記号を落とす（記号こそ探したいことがある）

対策は3段構え。完全一致（識別子そのもの）→ 部分語（分割した語）→ 逐次一致（文字列）。
索引側とクエリ側は必ず同じ規則で分割する。片側だけ分割しても呼び方の違い
（`build_incident_report` と `buildIncidentReport`）は吸収できない。

    python src/session15/code_search.py
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from ragkit.corpus import load_docs  # noqa: E402
from ragkit.models import Doc  # noqa: E402

_FENCE = re.compile(r"```(\w*)\n(.*?)```", re.DOTALL)
_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_DEF = re.compile(r"^\s*(?:def|class)\s+([A-Za-z_]\w*)", re.MULTILINE)
# キャメルケース・大文字略語・小文字語をそれぞれ1語として拾う
_PART = re.compile(r"[A-Z]+(?![a-z])|[A-Z][a-z0-9]*|[a-z0-9]+")

# 検索の手がかりにならない語（言語のキーワードと組み込み型）
CODE_KEYWORDS = frozenset({
    "def", "class", "return", "for", "if", "elif", "else", "while", "in", "is",
    "not", "and", "or", "none", "true", "false", "str", "int", "float", "bool",
    "dict", "list", "tuple", "set", "self", "import", "from", "as", "with",
    "try", "except", "finally", "raise", "pass", "lambda", "yield", "await",
})


@dataclass(frozen=True)
class CodeUnit:
    """検索単位にするコードのかたまり（この章では関数1つ）。"""

    unit_id: str
    doc_id: str
    doc_title: str
    lang: str
    name: str
    text: str

    @property
    def identifiers(self) -> frozenset[str]:
        return frozenset(identifiers(self.text))

    @property
    def tokens(self) -> frozenset[str]:
        return frozenset(code_tokens(self.text))


def split_identifier(name: str) -> list[str]:
    """`find_asset` → [find, asset] / `buildIncidentReport` → [build, incident, report]。"""
    out: list[str] = []
    for chunk in re.split(r"_+", name):
        out.extend(m.group(0).lower() for m in _PART.finditer(chunk))
    return [p for p in out if p]


def identifiers(text: str, *, drop_keywords: bool = True) -> list[str]:
    """コードに出てくる識別子そのもの（分割しない）。1文字の名前は捨てる。"""
    out: list[str] = []
    for m in _IDENT.finditer(text):
        name = m.group(0).lower()
        if len(name) < 2:
            continue
        if drop_keywords and name in CODE_KEYWORDS:
            continue
        out.append(name)
    return out


def code_tokens(text: str, *, drop_keywords: bool = True) -> list[str]:
    """識別子そのもの＋分割した部分語。完全一致と部分一致の両方を索引に載せる。"""
    out: list[str] = []
    for name in identifiers(text, drop_keywords=drop_keywords):
        out.append(name)
        parts = split_identifier(name)
        if len(parts) > 1:
            out.extend(parts)
    return out


def code_blocks(doc: Doc) -> list[tuple[str, str]]:
    """文書からフェンスで囲まれたコードを取り出す（言語, 中身）。"""
    return [(lang or "text", body) for lang, body in _FENCE.findall(doc.body)]


def code_units(doc: Doc) -> list[CodeUnit]:
    """コードブロックを関数単位に切る。最初の関数には先頭のコメントも含める。"""
    units: list[CodeUnit] = []
    for b_no, (lang, body) in enumerate(code_blocks(doc), start=1):
        starts = [m.start() for m in _DEF.finditer(body)] or [0]
        bounds = [0] + starts[1:] + [len(body)]
        for u_no, (s, e) in enumerate(zip(bounds[:-1], bounds[1:]), start=1):
            text = body[s:e].rstrip()
            if not text.strip():
                continue
            name_m = _DEF.search(text)
            units.append(CodeUnit(
                unit_id=f"{doc.doc_id}#C{b_no}{u_no}",
                doc_id=doc.doc_id,
                doc_title=doc.title,
                lang=lang,
                name=name_m.group(1) if name_m else "(無名)",
                text=text,
            ))
    return units


def search_code(units: list[CodeUnit], query: str, *, exact_weight: float = 3.0,
                partial_weight: float = 1.0) -> list[tuple[float, CodeUnit]]:
    """完全一致（識別子そのもの）を重く、部分語を軽く採点する。"""
    raw = [t for t in _IDENT.findall(query) if len(t) >= 2]
    wanted = [t.lower() for t in raw]
    # 分割は小文字化する前の文字列に対して行う（先に小文字化するとキャメルケースの
    # 境界が消え、`buildIncidentReport` が1語のままになって索引側と噛み合わない）
    parts = {p for t in raw for p in split_identifier(t)}
    scored: list[tuple[float, CodeUnit]] = []
    for u in units:
        exact = sum(1 for w in wanted if w in u.identifiers)
        partial = sum(1 for p in parts if p in u.tokens)
        score = exact_weight * exact + partial_weight * partial
        if score > 0:
            scored.append((score, u))
    scored.sort(key=lambda x: (-x[0], x[1].unit_id))
    return scored


def literal_search(units: list[CodeUnit], text: str) -> list[CodeUnit]:
    """記号を含む文字列は、索引を通さず逐次一致で探す（grep 相当の最後の手段）。"""
    return [u for u in units if text in u.text]


def main() -> None:
    docs = load_docs()
    units = [u for d in docs for u in code_units(d)]
    print(f"コードを含む文書: {len({u.doc_id for u in units})} 件 / コード単位: {len(units)} 個")
    for u in units:
        print(f"  {u.unit_id} {u.name}（{u.doc_title}）{len(u.text.splitlines())} 行")

    line = "def find_asset(asset_tag: str) -> dict | None:"
    print(f"\n--- 1行のトークナイズ ---\n{line}")
    print(f"識別子のみ  : {identifiers(line)}")
    print(f"索引に載せる: {code_tokens(line)}")

    for q in ["find_asset", "asset", "report", "buildIncidentReport"]:
        hits = search_code(units, q)
        got = ", ".join(f"{u.name}({s:.0f})" for s, u in hits) or "（0件）"
        print(f"\nクエリ「{q}」-> {got}")

    for text in ["==", 'row["asset_tag"]']:
        hits = literal_search(units, text)
        print(f"逐次一致「{text}」-> {[u.name for u in hits] or '（0件）'}")


if __name__ == "__main__":
    main()

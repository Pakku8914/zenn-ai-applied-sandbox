"""いま家にある食材（在庫）と、作れるレシピ（中間プロジェクト1で足した部分）。

在庫の合成規則（本プロジェクトで決めた値）：
1. 材料は2種類。冷蔵庫の写真は利用者ごとに最新の1回分（撮り直したら置き換える）、レシートは取り込んだものすべて
2. 名前は前後の空白を除き、末尾の入り数「（10個入り）」だけを外して数量に掛ける。それ以外は書き換えない
   （NFKC や括弧の除去をすると「めんつゆ（3倍濃縮）」のような食材辞書の名前と一致しなくなる）
3. 要確認のものは在庫に混ぜず、to_review に分ける
   - 写真：セッション4の issues が付いた食材
   - レシート：その行の issues・レシート全体の issues（index が null）・名前が食材辞書に無い・個数が1未満
4. 確認済みは名前ごとに1行にまとめ、同じ単位の数量は足す（単位が違えば並べる）。並びは最初に出てきた順
5. 数量は目安。写真に写っている物をレシートでも数えることがあるので、レシピ探しには名前だけを使う
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from kondate.data import load_recipes
from src.mid01.fridge import Ingredient, ingredient_dictionary
from src.mid01.receipt import ReceiptItem
from src.mid01.recipes import MAX_INGREDIENTS, SearchRecipesIn, search_recipes

PACK = re.compile(r"[（(]\s*(\d+)\s*(個|本|枚|切れ|袋)入り?\s*[）)]$")  # \d は全角数字にも合う
RECEIPT_UNIT = "点"   # 入り数の書いていないレシートの行は「買った点数」で数える
CENT = Decimal("0.01")


def split_label(label: str) -> tuple[str, tuple[int, str] | None]:
    """表記から (名前, 入り数) を取り出す。例：「卵（10個入り）」→ ("卵", (10, "個"))、「牛乳」→ ("牛乳", None)"""
    text = label.strip()
    m = PACK.search(text)
    if m is None or m.start() == 0:
        return text, None
    return text[: m.start()].strip(), (int(m[1]), m[2])


@dataclass(frozen=True)
class FridgeSnapshot:
    """冷蔵庫の写真1回分の読み取り（セッション4の ingredients と issues）。"""
    ingredients: list[Ingredient]
    issues: list[dict]


@dataclass(frozen=True)
class Entry:
    """在庫の材料1件（写真の食材1件、またはレシートの1行）。"""
    name: str
    amount: Decimal
    unit: str
    source: dict               # {"type": "fridge", "index": 0} か {"type": "receipt", "id": "rcp_…", "index": 2}
    reasons: tuple[str, ...]   # 空なら確認済み


def fridge_entries(snap: FridgeSnapshot) -> list[Entry]:
    out = []
    for index, ing in enumerate(snap.ingredients):
        name, _ = split_label(ing.name)
        reasons = tuple(dict.fromkeys(i["reason"] for i in snap.issues if i["index"] == index))
        out.append(Entry(name, Decimal(str(ing.amount)), ing.unit, {"type": "fridge", "index": index}, reasons))
    return out


def receipt_entries(receipt_id: str, items: list[ReceiptItem], issues: list[dict]) -> list[Entry]:
    whole = [i["reason"] for i in issues if i["index"] is None]  # レシート全体が疑わしい（日付・合計・PDF の文字）
    known = ingredient_dictionary()
    out = []
    for index, item in enumerate(items):
        name, pack = split_label(item.name)
        reasons = whole + [i["reason"] for i in issues if i["index"] == index]
        if name not in known:
            reasons.append("unknown_name")
        if item.quantity < 1:
            reasons.append("invalid_quantity")
        amount, unit = (item.quantity * pack[0], pack[1]) if pack else (item.quantity, RECEIPT_UNIT)
        source = {"type": "receipt", "id": receipt_id, "index": index}
        out.append(Entry(name, Decimal(amount), unit, source, tuple(dict.fromkeys(reasons))))
    return out


def number(value: Decimal) -> float:
    return float(value.quantize(CENT, rounding=ROUND_HALF_UP))  # 小数第2位で四捨五入（シリーズ共通の丸め）


def compose(entries: list[Entry]) -> dict:
    """材料を在庫にまとめる。要確認は足し合わせず、1件ずつ to_review に並べる。"""
    merged: dict[str, dict] = {}
    to_review: list[dict] = []
    for e in entries:
        if e.reasons:
            to_review.append({"name": e.name, "amount": number(e.amount), "unit": e.unit,
                              "source": e.source, "reasons": list(e.reasons)})
            continue
        row = merged.setdefault(e.name, {"amounts": {}, "sources": []})
        row["amounts"][e.unit] = row["amounts"].get(e.unit, Decimal(0)) + e.amount
        row["sources"].append(e.source)
    items = [
        {"name": name,
         "amounts": [{"amount": number(a), "unit": u} for u, a in row["amounts"].items()],
         "sources": row["sources"]}
        for name, row in merged.items()
    ]
    return {"items": items, "to_review": to_review}


def book_index(books: dict[str, list[dict]]) -> dict[str, list[dict]]:
    """取り込んだレシピ本の目録を、レシピ ID → 載っている場所（文書とページ）の一覧に引き直す。"""
    index: dict[str, list[dict]] = {}
    for document_id, recipes in books.items():
        for r in recipes:
            index.setdefault(r["id"], []).append({"document_id": document_id, "page": r["page"]})
    return index


def find_recipes(names: list[str], books: dict[str, list[dict]], scope: str,
                 max_minutes: int | None, limit: int) -> list[dict]:
    """確認済みの食材名で search_recipes を呼ぶ。scope="books" なら取り込んだ本に載っているレシピだけを探す。"""
    if not names:
        return []  # 食材が無いまま探すと、食材と関係なく調理時間の短い順に並んでしまう
    index = book_index(books)
    pool = None if scope == "all" else tuple(r for r in load_recipes() if r["id"] in index)
    args = SearchRecipesIn(ingredients=names[:MAX_INGREDIENTS], max_minutes=max_minutes, limit=limit)
    return [{**r, "in_books": index.get(r["id"], [])} for r in search_recipes(args, pool)["recipes"]]

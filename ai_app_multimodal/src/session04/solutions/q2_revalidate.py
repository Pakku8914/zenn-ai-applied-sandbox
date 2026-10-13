"""問題2：構造化出力が保証すること・しないことを、Pydantic の再検証で仕分ける。

    docker compose exec api python -m src.session04.solutions.q2_revalidate
"""

from __future__ import annotations

import json

from pydantic import ValidationError

from src.session04.models import FridgeScan

OK_ITEM = {"name": "キャベツ", "quantity": "1/2玉", "amount": 0.5, "unit": "玉", "confidence": 0.94, "category": "野菜"}

# 構造化出力が防ぐ誤り（JSON の形・型・必須の項目）。これ以外は「値の誤り」として扱う
SHAPE_ERRORS = {"missing", "float_parsing", "float_type", "string_type", "list_type", "model_type", "dict_type"}


def one(**over) -> str:
    """OK_ITEM を1件だけ持つ応答の JSON。値に None を渡した項目は取り除く。"""
    item = {k: v for k, v in {**OK_ITEM, **over}.items() if v is not None}
    return json.dumps({"ingredients": [item]}, ensure_ascii=False)


CASES = [
    ("正常", one()),
    ("confidence が 1.2", one(confidence=1.2)),
    ("amount が 0", one(amount=0)),
    ("name が空", one(name="")),
    ("unit が無い", one(unit=None)),
    ("confidence が文字列", one(confidence="高い")),
    ("途中で切れた JSON", '{"ingredients": [{"name": "キャベツ", "quantity": "1/2'),
]


def kind_of(error_type: str) -> str:
    if error_type == "json_invalid":
        return "形の誤り：構造化出力でも max_tokens で切れると起きる"
    if error_type in SHAPE_ERRORS:
        return "形の誤り：構造化出力で防げる"
    return "値の誤り：構造化出力では防げない"


def judge(text: str) -> str:
    try:
        scan = FridgeScan.model_validate_json(text)
    except ValidationError as e:
        parts = [f"{'.'.join(str(p) for p in err['loc']) or '(全体)'}: {err['type']}（{kind_of(err['type'])}）"
                 for err in e.errors()]
        return "NG " + "、".join(parts)
    return f"OK（食材 {len(scan.ingredients)} 件）"


def main() -> None:
    for label, text in CASES:
        print(f"{label}: {judge(text)}")


if __name__ == "__main__":
    main()

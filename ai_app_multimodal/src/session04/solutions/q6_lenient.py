"""問題6（発展）：一部の項目だけが壊れているとき、残りを生かして壊れた項目を要確認に回す。

    docker compose exec api python -m src.session04.solutions.q6_lenient
"""

from __future__ import annotations

import json

from pydantic import ValidationError

from src.session04.models import Ingredient

MSG_INVALID_ITEM = "読み取り結果の一部が壊れていました。この食材は手で入力してください"


class TooBroken(Exception):
    """全体を失敗（502 か再試行）として扱うべき応答。"""


def parse_lenient(text: str) -> tuple[list[Ingredient], list[dict]]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        raise TooBroken("JSON として読めない") from None
    raw_items = data.get("ingredients") if isinstance(data, dict) else None
    if not isinstance(raw_items, list):
        raise TooBroken("ingredients の配列が無い")

    good: list[Ingredient] = []
    issues: list[dict] = []
    for raw in raw_items:
        try:
            good.append(Ingredient.model_validate(raw))
        except ValidationError:
            name = raw.get("name") if isinstance(raw, dict) else None
            # ingredients に入らない食材なので index は付けない（None）
            issues.append({"index": None, "name": name if isinstance(name, str) else "",
                           "reason": "invalid_item", "message": MSG_INVALID_ITEM})
    if len(good) * 2 < len(raw_items):
        raise TooBroken(f"使える項目が {len(good)}/{len(raw_items)} 件で、半分に届かない")
    return good, issues


def item(name: str, **over) -> dict:
    d = {"name": name, "quantity": "1個", "amount": 1, "unit": "個", "confidence": 0.9, "category": "野菜"}
    d.update(over)
    return {k: v for k, v in d.items() if v is not None}


CASES = [
    ("2件が壊れている", [item("キャベツ"), item("鶏むね肉", confidence=1.5), item("卵", unit=None), item("にんじん"), item("牛乳")]),
    ("3件が壊れている", [item("キャベツ", confidence=-0.1), item("鶏むね肉", confidence=1.5), item("卵", unit=None),
                        item("にんじん"), item("牛乳")]),
    ("JSON ではない", "食材は キャベツ と 卵 です"),
]


def main() -> None:
    for label, payload in CASES:
        text = payload if isinstance(payload, str) else json.dumps({"ingredients": payload}, ensure_ascii=False)
        try:
            good, issues = parse_lenient(text)
        except TooBroken as e:
            print(f"{label}: 502（{e}）")
            continue
        print(f"{label}: 使える {len(good)} 件（{'、'.join(i.name for i in good)}）"
              f"／要確認に回した {len(issues)} 件（{'、'.join(i['name'] for i in issues)}）")


if __name__ == "__main__":
    main()

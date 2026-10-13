"""問題5：前処理 → 読み取り → 要確認 → 応答の組み立て → 確認済みの食材だけで検索、を1回通す。

    docker compose exec api python -m src.review01.solutions.q5_response
"""

from __future__ import annotations

import asyncio
import json

from kondate.llm import ChatResult, FakeProvider, Usage
from src.review01 import samples
from src.review01.kit import (
    PreparedImage, ScanResult, confirmed_names, find_issues, prepare_image, scan_fridge, search_recipes, to_search_args,
)

ITEMS = [  # (名前, confidence)
    (" キャベツ ", 0.94),  # 前後の空白は Name 型の strip_whitespace で落ちる
    ("鶏ムネ肉", 0.9),      # 食材辞書の表記は「鶏むね肉」
    ("にんじん", 0.42),
    ("卵", 0.6),            # 0.6 は「未満」ではない
    ("キャベツ", 0.88),     # 同じ食材が2回読まれた
]


def fake_answer() -> ChatResult:
    items = [{"name": n, "quantity": "1個", "amount": 1, "unit": "個", "confidence": c, "category": "野菜"} for n, c in ITEMS]
    return ChatResult(json.dumps({"ingredients": items}, ensure_ascii=False), [], "end_turn", Usage(1668, 194))


def build_response(prepared: PreparedImage, result: ScanResult) -> dict:
    """/api/fridge/scan の応答。項目と順序は API契約のとおり。"""
    issues = find_issues(result.scan.ingredients)
    return {
        "ingredients": [i.model_dump() for i in result.scan.ingredients],
        "needs_review": bool(issues),
        "issues": issues,
        "image": prepared.info(),
        "usage": {"input_tokens": result.usage.input_tokens, "output_tokens": result.usage.output_tokens},
    }


async def run() -> None:
    prepared = prepare_image(samples.fridge())                                # セッション3
    result = await scan_fridge(FakeProvider([fake_answer()]), prepared.data)  # セッション4
    body = build_response(prepared, result)
    names = [i["name"] for i in body["ingredients"]]
    print(f"応答の項目: {', '.join(body)}")
    print(f"ingredients: {'、'.join(names)}（{len(names)} 件）")
    print(f"needs_review: {body['needs_review']}")
    issues = " ／ ".join(f"{i['index']} {i['name']} {i['reason']}" for i in body["issues"])
    print(f"issues: {issues}")
    img = body["image"]
    print(f"image: sent_size={img['sent_size']}・exif_removed={img['exif_removed']}・bytes={img['bytes']}")
    print(f"usage: input_tokens={body['usage']['input_tokens']}・output_tokens={body['usage']['output_tokens']}")

    confirmed = confirmed_names(result.scan.ingredients, body["issues"])  # 応答の issues をそのまま使う
    print(f"確認済みの食材: {'、'.join(confirmed)}")
    found = search_recipes(to_search_args(confirmed))["recipes"]
    print(f"search_recipes: {', '.join(r['id'] for r in found)}")


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()

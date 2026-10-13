"""読み取った食材のうち、人に確かめてもらうもの（要確認）を選ぶ（セッション4）。

要確認の基準（本書で固定する値）：
- confidence が REVIEW_CONFIDENCE（0.6）未満 → reason "low_confidence"
- 名前が食材辞書（data/recipes.json に出てくる食材名の集合）に無い → reason "unknown_name"
要確認の食材も ingredients からは消さない。issues に index（ingredients の位置）で印を付ける。
"""

from __future__ import annotations

from functools import lru_cache

from kondate.data import load_recipes
from src.session04.models import Ingredient

REVIEW_CONFIDENCE = 0.6
MSG_LOW_CONFIDENCE = "読み取りの確からしさが低い食材です。写真と合っているか確かめてください"
MSG_UNKNOWN_NAME = "食材辞書にない名前です。名前が正しいか確かめてください"


@lru_cache
def ingredient_dictionary() -> frozenset[str]:
    """レシピデータに出てくる食材名の集合。ここに無い名前では、レシピを探しても見つからない。"""
    return frozenset(i["name"] for r in load_recipes() for i in r["ingredients"])


def find_issues(ingredients: list[Ingredient], dictionary: frozenset[str] | None = None) -> list[dict]:
    known = ingredient_dictionary() if dictionary is None else dictionary
    issues: list[dict] = []
    for index, ing in enumerate(ingredients):
        if ing.confidence < REVIEW_CONFIDENCE:
            issues.append({"index": index, "name": ing.name, "reason": "low_confidence", "message": MSG_LOW_CONFIDENCE})
        if ing.name not in known:
            issues.append({"index": index, "name": ing.name, "reason": "unknown_name", "message": MSG_UNKNOWN_NAME})
    return issues


def confirmed_names(ingredients: list[Ingredient], issues: list[dict]) -> list[str]:
    """要確認の印が1つも付いていない食材の名前（重複を除き、順序は保つ）。"""
    flagged = {i["index"] for i in issues}
    return list(dict.fromkeys(ing.name for index, ing in enumerate(ingredients) if index not in flagged))

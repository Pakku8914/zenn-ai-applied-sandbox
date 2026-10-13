"""読み取った食材のうち、人に確かめてもらうもの（要確認）を選ぶ（セッション4の review.py の写し）。"""

from __future__ import annotations

from functools import lru_cache

from kondate.data import load_recipes
from src.final.models import Ingredient

REVIEW_CONFIDENCE = 0.6
MSG_LOW_CONFIDENCE = "読み取りの確からしさが低い食材です。写真と合っているか確かめてください"
MSG_UNKNOWN_NAME = "食材辞書にない名前です。名前が正しいか確かめてください"


@lru_cache
def ingredient_dictionary() -> frozenset[str]:
    """レシピデータに出てくる食材名の集合。"""
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

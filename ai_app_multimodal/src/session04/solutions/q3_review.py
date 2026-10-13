"""問題3：要確認の振り分けと、しきい値を動かしたときの件数の変化。

    docker compose exec api python -m src.session04.solutions.q3_review
"""

from __future__ import annotations

from src.session04.models import Ingredient
from src.session04.review import ingredient_dictionary

SCANNED = [("キャベツ", 0.94), ("鶏ムネ肉", 0.9), ("にんじん", 0.42), ("ズッキーニ", 0.35), ("卵", 0.6), ("牛乳", 0.81)]


def make(name: str, confidence: float) -> Ingredient:
    return Ingredient(name=name, quantity="1個", amount=1, unit="個", confidence=confidence, category="野菜")


def review(ingredients: list[Ingredient], threshold: float, dictionary: frozenset[str]) -> list[tuple[Ingredient, list[str]]]:
    """要確認の食材と、その理由（複数あれば全部）を ingredients の順に返す。"""
    flagged = []
    for ing in ingredients:
        reasons = []
        if ing.confidence < threshold:  # 「未満」。ちょうどしきい値のものは要確認にしない
            reasons.append(f"確からしさが低い（{ing.confidence}）")
        if ing.name not in dictionary:
            reasons.append("辞書にない")
        if reasons:
            flagged.append((ing, reasons))
    return flagged


def main() -> None:
    ingredients = [make(n, c) for n, c in SCANNED]
    dictionary = ingredient_dictionary()
    for threshold in (0.6, 0.85):
        flagged = review(ingredients, threshold, dictionary)
        print(f"しきい値 {threshold}: 要確認 {len(flagged)} 件")
        for ing, reasons in flagged:
            print(f"  {ing.name}: {'・'.join(reasons)}")


if __name__ == "__main__":
    main()

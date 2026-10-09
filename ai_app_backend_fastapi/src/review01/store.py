"""レシピとユーザーをメモリに持つ入れ物（session02/store.py のコピー）。"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from kondate.data import load_recipes, load_users


@dataclass(frozen=True)
class DataStore:
    recipes: Mapping[str, dict]
    users: Mapping[str, dict]

    @classmethod
    def from_rows(cls, recipes: Iterable[dict], users: Iterable[dict] = ()) -> DataStore:
        return cls(recipes={r["id"]: r for r in recipes}, users={u["id"]: u for u in users})

    @classmethod
    def load(cls) -> DataStore:
        return cls.from_rows(load_recipes(), load_users())

    def get_recipe(self, recipe_id: str) -> dict | None:
        return self.recipes.get(recipe_id)

    def get_user(self, user_id: str) -> dict | None:
        return self.users.get(user_id)

    def find_recipes(
        self, *, ingredient: str | None = None, max_minutes: int | None = None, tags: Sequence[str] = ()
    ) -> list[dict]:
        """食材は部分一致・調理時間は以下・タグは AND。id の昇順で返す。"""
        wanted = set(tags)
        hits: list[dict] = []
        for recipe_id in sorted(self.recipes):
            recipe = self.recipes[recipe_id]
            if ingredient is not None and not any(ingredient in i["name"] for i in recipe["ingredients"]):
                continue
            if max_minutes is not None and recipe["minutes"] > max_minutes:
                continue
            if not wanted <= set(recipe["tags"]):
                continue
            hits.append(recipe)
        return hits

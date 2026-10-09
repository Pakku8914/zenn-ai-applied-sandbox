"""練習問題3の解答：LLM が送ってきそうな入力が、どこで止まるかの予想。

"schema" = Pydantic の検証で止まる／"tool" = 検証は通り、ツールの中で ToolError になる／"ok" = 成功する
"""

from __future__ import annotations

INPUTS: dict[str, tuple[str, dict]] = {
    "a": ("set_timer", {"minutes": "15", "label": "煮込み"}),
    "b": ("set_timer", {"minutes": 15.5, "label": "煮込み"}),
    "c": ("get_recipe", {"recipe_id": "R121"}),
    "d": ("convert_units", {"amount": 200, "from_unit": "g", "to_unit": "カップ"}),
    "e": ("convert_units", {"amount": 1, "from_unit": "合", "to_unit": "ml"}),
    "f": ("search_recipes", {"ingredients": ["卵"], "exclude_allergens": ["卵"], "tags": ["和食"]}),
    "g": ("make_shopping_list", {"recipe_ids": []}),
    "h": ("search_recipes", {"ingredients": ["鶏むね肉"], "max_minutes": 0}),
}

PREDICTIONS: dict[str, str] = {
    "a": "ok",  # lax モードでは数字だけの文字列 "15" は 15 に変換される
    "b": "schema",  # 小数部のある float は int にしない
    "c": "tool",  # 形式（R + 3桁）は正しいが、R121 は存在しない
    "d": "tool",  # 単位はどちらも候補にあるが、重さ → 体積は換算しない
    "e": "schema",  # 「合」は単位の候補（Literal）に無い
    "f": "ok",  # 0件になるかもしれないが、入力としては正しい
    "g": "schema",  # min_length=1
    "h": "schema",  # ge=1
}

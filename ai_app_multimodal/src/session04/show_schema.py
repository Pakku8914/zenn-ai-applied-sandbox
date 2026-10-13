"""FridgeScan のスキーマを、transform_schema で変換する前と後で見比べる。

    docker compose exec api python -m src.session04.show_schema
"""

from __future__ import annotations

from src.session04.models import FRIDGE_SCHEMA, FridgeScan

# 値の範囲・長さの制約（変換前のスキーマにあるキーワード）
CONSTRAINTS = {"name": ("minLength", "maxLength"), "amount": ("exclusiveMinimum",), "confidence": ("minimum", "maximum")}


def main() -> None:
    before = FridgeScan.model_json_schema()["$defs"]["Ingredient"]["properties"]
    after = FRIDGE_SCHEMA["$defs"]["Ingredient"]
    print(f"必須の項目: {', '.join(after['required'])}")
    print(f"additionalProperties: {after['additionalProperties']}")
    for field, keys in CONSTRAINTS.items():
        prop = after["properties"][field]
        was = ", ".join(f"{k}={before[field][k]}" for k in keys)
        kept = [k for k in keys if k in prop]
        moved = [k for k in keys if k in prop.get("description", "")]
        print(f"{field}: {was} → スキーマに残った制約: {', '.join(kept) or 'なし'}（説明文に書き写された: {', '.join(moved) or 'なし'}）")


if __name__ == "__main__":
    main()

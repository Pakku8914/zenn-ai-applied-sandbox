"""JSON Schema から決定的なサンプル値を作る（構造化出力の既定応答用）。

hints は「プロパティ名 → 値」の辞書。
- スキーマが配列のプロパティに配列のヒントを与えると、その配列をそのまま使う
- スカラーのプロパティに配列のヒントを与えると、配列要素 i 番目の値として i 番目を使う
- 特別なキー "_array_len" は、ヒントの無い配列を何要素で作るか（既定 1、minItems / maxItems が優先）
"""

from __future__ import annotations

from typing import Any


def _resolve_ref(schema: dict, root: dict) -> dict:
    ref = schema.get("$ref")
    if not ref or not ref.startswith("#/"):
        return schema
    node: Any = root
    for part in ref[2:].split("/"):
        node = node[part]
    return node


def _type_of(schema: dict) -> str:
    stype = schema.get("type")
    if isinstance(stype, list):
        stype = next((t for t in stype if t != "null"), "null")
    if stype is None:
        stype = "object" if "properties" in schema else "string"
    return stype


def generate(schema: dict, hints: dict | None = None, *, root: dict | None = None,
             key: str | None = None, index: int = 0, depth: int = 0) -> Any:
    hints = hints or {}
    root = root or schema
    schema = _resolve_ref(schema, root)

    for comb in ("anyOf", "oneOf", "allOf"):
        if comb in schema and schema[comb]:
            options = [s for s in schema[comb] if _resolve_ref(s, root).get("type") != "null"]
            return generate((options or schema[comb])[0], hints, root=root, key=key, index=index, depth=depth + 1)

    stype = _type_of(schema)
    if key is not None and key in hints:
        value = hints[key]
        if isinstance(value, list) and stype != "array":
            return value[index % len(value)] if value else None
        return value

    if depth > 8:
        return None
    if "const" in schema:
        return schema["const"]
    if "enum" in schema and schema["enum"]:
        return schema["enum"][index % len(schema["enum"])]

    if stype == "object":
        return {
            name: generate(sub, hints, root=root, key=name, index=index, depth=depth + 1)
            for name, sub in schema.get("properties", {}).items()
        }
    if stype == "array":
        count = max(1, int(schema.get("minItems", 1)), int(hints.get("_array_len", 1)))
        if "maxItems" in schema:
            count = min(count, int(schema["maxItems"]))
        items = schema.get("items", {"type": "string"})
        return [generate(items, hints, root=root, key=key, index=i, depth=depth + 1) for i in range(count)]
    if stype == "string":
        fmt = schema.get("format")
        if fmt == "date":
            return "2026-10-02"
        if fmt == "date-time":
            return "2026-10-02T09:00:00+09:00"
        return f"{key or '値'}のサンプル{index + 1}"
    if stype == "integer":
        return int(schema.get("minimum", 1))
    if stype == "number":
        return float(schema.get("minimum", 1))
    if stype == "boolean":
        return True
    return None

"""ツール定義の正規化ダイジェスト（Python 版）

TypeScript 版（node/src/session13/schema-digest.ts）と同じ形・同じキー名で出します。
mcp 2.0 のモデルは属性が snake_case（input_schema / read_only_hint）なので、
ダイジェストのキー名（camelCase）へ翻訳するのがこのモジュールの仕事です。
"""

from __future__ import annotations

from typing import Any


def digest_tools(tools: list[Any]) -> list[dict[str, Any]]:
    return sorted((_digest(tool) for tool in tools), key=lambda item: item["name"])


def _digest(tool: Any) -> dict[str, Any]:
    schema: dict[str, Any] = tool.input_schema or {}
    properties: dict[str, Any] = schema.get("properties", {})
    required = set(schema.get("required", []))
    annotations = tool.annotations

    return {
        "name": tool.name,
        "title": tool.title,
        "annotations": {
            "readOnlyHint": getattr(annotations, "read_only_hint", None),
            "destructiveHint": getattr(annotations, "destructive_hint", None),
            "idempotentHint": getattr(annotations, "idempotent_hint", None),
            "openWorldHint": getattr(annotations, "open_world_hint", None),
        },
        "args": [
            {
                "name": name,
                "required": name in required,
                "hasDescription": isinstance(properties[name].get("description"), str),
            }
            # Python の sorted はコードポイント順（TypeScript 版の compareStrings と同じ）
            for name in sorted(properties)
        ],
    }

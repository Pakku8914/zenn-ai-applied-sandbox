#!/usr/bin/env python3
"""スキーマを「宣言」から「検証」に変える薄い層（セッション4）。

agentkit の `ToolRegistry` は schema を LLM に渡すだけで、引数の検査はしない。
つまり「スキーマに enum を書いた」だけでは何も守られない。検証は呼び出し口の
責務なので、agentkit を変更せずにこの層をかぶせる（API契約を壊さないため）。

エラーメッセージは必ず次の2つを含める。
  1. 何が悪かったか（どの引数の、どの値が）
  2. 次に何をすべきか（許容値・必要な引数・範囲）
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agentkit.models import ToolCall, ToolResult  # noqa: E402
from agentkit.tools import ToolError, ToolRegistry  # noqa: E402

TYPE_JA = {"string": "文字列", "integer": "整数", "number": "数値",
           "boolean": "真偽値", "array": "配列", "object": "オブジェクト"}
PY_TYPES: dict[str, type | tuple[type, ...]] = {
    "string": str, "integer": int, "number": (int, float),
    "boolean": bool, "array": list, "object": dict,
}


def validate_args(schema: dict, args: dict) -> dict:
    """スキーマで引数を検証し、既定値を補完した引数を返す。

    違反は `ToolError` で返す（例外の型名ではなく、モデルが読める日本語で）。
    ツールのスキーマでは「知らない引数は受け付けない」を既定にする。
    未知の引数を黙って捨てると、モデルは「渡したのに効かない」を学習してしまう。
    """
    props: dict = schema.get("properties", {})
    required: list = schema.get("required", [])
    usable = ", ".join(props) or "（なし）"

    for key in args:
        if key not in props:
            raise ToolError(f"引数 '{key}' は使えません。この中から指定してください: {usable}")
    for key in required:
        if key not in args:
            raise ToolError(
                f"必須の引数 '{key}' がありません。"
                f"次の引数を必ず指定してください: {', '.join(required)}")

    checked = dict(args)
    for key, spec in props.items():
        if key not in checked:
            if "default" in spec:
                checked[key] = spec["default"]
            continue
        value = checked[key]

        expected = spec.get("type")
        if expected in PY_TYPES:
            if expected in ("integer", "number") and isinstance(value, bool):
                ok = False  # bool は int の仲間だが、金額として受け取ってはいけない
            else:
                ok = isinstance(value, PY_TYPES[expected])
            if not ok:
                raise ToolError(
                    f"引数 '{key}' は{TYPE_JA[expected]}で指定してください"
                    f"（受け取った値: {value!r} / 型: {type(value).__name__}）。")

        if "enum" in spec and value not in spec["enum"]:
            raise ToolError(
                f"引数 '{key}' は次のいずれかを指定してください: "
                f"{', '.join(map(str, spec['enum']))}（受け取った値: {value}）。")

        lo, hi = spec.get("minimum"), spec.get("maximum")
        if lo is not None and hi is not None and not (lo <= value <= hi):
            raise ToolError(
                f"引数 '{key}' は {lo} 以上 {hi} 以下で指定してください"
                f"（受け取った値: {value}）。")
        if lo is not None and hi is None and value < lo:
            raise ToolError(
                f"引数 '{key}' は {lo} 以上で指定してください（受け取った値: {value}）。")
        if hi is not None and lo is None and value > hi:
            raise ToolError(
                f"引数 '{key}' は {hi} 以下で指定してください（受け取った値: {value}）。")

        if "maxLength" in spec and isinstance(value, str) and len(value) > spec["maxLength"]:
            raise ToolError(
                f"引数 '{key}' は {spec['maxLength']} 文字以内で指定してください"
                f"（受け取った値: {len(value)} 文字）。")
    return checked


class SchemaCheckedRegistry(ToolRegistry):
    """ツールを実行する前にスキーマで引数を検証するレジストリ。

    agentkit の `ToolRegistry` を継承し、`call` だけを差し替える。
    検証に落ちた呼び出しは**実装に到達しない**ので、副作用も起きない。
    """

    def call(self, call: ToolCall) -> ToolResult:
        tool = self.get(call.name)
        if tool is None:
            # 未登録ツールの扱いは基底クラスに任せる（使えるツール名を返してくれる）
            return super().call(call)
        try:
            args = validate_args(tool.schema, call.args)
        except ToolError as exc:
            return ToolResult(call.call_id, False, "", str(exc))
        return super().call(ToolCall(call.call_id, call.name, args))

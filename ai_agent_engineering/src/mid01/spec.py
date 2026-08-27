#!/usr/bin/env python3
"""調査エージェントが持つ道具と、そこから生成するツール仕様書（成果物①）。

    python src/mid01/spec.py

道具は4つだけにした。読み取り3つ（get_policy / find_expenses / search_docs）と
書き込み1つ（write_file。作業領域の中だけ）である。
承認が必要な操作（submit_expense / send_message）は**持たせない**。
理由は解答章の「設計判断の記録」に書いてある。

実装は S04 の改善版（`goodtools.py`）をそのまま使う。agentkit の素の道具を使わない
のは、素の `get_policy` のエラーが `is_actionable()` を満たさないため（候補は出すが
「次に何をすべきか」を書いていない）。この一点で、失敗したときの振る舞いが変わる。
"""

from __future__ import annotations

from _paths import setup

ROOT = setup()

from agentkit.biztools import search_docs, write_file  # noqa: E402
from agentkit.models import ToolCall, ToolResult  # noqa: E402
from agentkit.tools import Tool  # noqa: E402
from goodtools import (FIND_EXPENSES_DESC, FIND_EXPENSES_SCHEMA,  # noqa: E402
                       POLICY_DESC, POLICY_SCHEMA, SEARCH_DESC, SEARCH_SCHEMA,
                       find_expenses, get_policy_v2, render_tool_spec)
from toolschema import SchemaCheckedRegistry  # noqa: E402

from machine import MATERIAL_TOOLS, STATE_TOOLS  # noqa: E402

WRITE_DESC = (
    "作業領域にファイルを書きます（データが増える副作用あり）。"
    "使う場面: 完成したレポート・引き継ぎメモを保存する。"
    "使わない場面: 途中の思考を書き留める（進捗は状態が持つので不要です）。"
    "同じパスに同じ内容を書けば結果は同じです（冪等）。"
)
WRITE_SCHEMA = {
    "type": "object",
    "properties": {
        "path": {"type": "string", "maxLength": 80,
                 "description": "workspace/ からの相対パス（例: mid01/report.md）"},
        "content": {"type": "string", "maxLength": 8000, "description": "書き込む本文"},
    },
    "required": ["path", "content"],
}


def build_registry() -> SchemaCheckedRegistry:
    """調査エージェントのレジストリ（読み取り3つ＋書き込み1つ）。

    `SchemaCheckedRegistry`（S04）を使うので、スキーマ違反は**実装に到達しない**。
    """
    return SchemaCheckedRegistry([
        Tool("find_expenses", FIND_EXPENSES_DESC, FIND_EXPENSES_SCHEMA, find_expenses,
             tags=("read",)),
        Tool("get_policy", POLICY_DESC, POLICY_SCHEMA, get_policy_v2, tags=("read",)),
        Tool("search_docs", SEARCH_DESC, SEARCH_SCHEMA, search_docs, tags=("read",)),
        Tool("write_file", WRITE_DESC, WRITE_SCHEMA, write_file, idempotent=True,
             tags=("write",)),
    ])


class BreakingRegistry(SchemaCheckedRegistry):
    """指定した道具が必ず内部エラーになるレジストリ（異常系の再現用）。

    agentkit の `ToolRegistry.call` は想定外の例外を
    `ToolResult(ok=False, error="内部エラー（型名）")` に変換する。その形をそのまま返す。
    このメッセージは `is_actionable()` を満たさない（候補も次の一手も書けない）。
    **直せない失敗をどう扱うか**が、このレジストリで試せるようになる。
    """

    def __init__(self, tools=None, *, broken: tuple[str, ...] = ()) -> None:
        super().__init__(tools or [])
        self.broken = tuple(broken)

    def call(self, call: ToolCall) -> ToolResult:
        if call.name in self.broken:
            return ToolResult(call.call_id, False, "", "内部エラー（TimeoutError）")
        return super().call(call)


def build_breaking_registry(broken: tuple[str, ...] = ("find_expenses",)) -> BreakingRegistry:
    """同じ道具立てのまま、指定した道具だけを壊したレジストリを作る。"""
    base = build_registry()
    tools = [base.get(name) for name in base.names()]
    return BreakingRegistry(tools, broken=broken)


def render_spec_md(registry=None, state_tools=None) -> str:
    """ツール仕様書（成果物①）。宣言から生成するので実装とずれない。

    S04 の `render_tool_spec()` に、この章で決めた2列を足したもの。
      使える状態   … その道具を呼べる段階（状態機械の許可リストから引く）
      根拠に採用   … 結果を状態に取り込むか（取り込まないものは報告に書かせない）
    """
    registry = registry or build_registry()
    state_tools = state_tools or STATE_TOOLS
    lines = ["| ツール | 副作用 | 冪等 | 承認 | 必須の引数 | 使える状態 | 根拠に採用 |",
             "| :--- | :--- | :--- | :--- | :--- | :--- | :--- |"]
    for name in registry.names():
        tool = registry.get(name)
        if tool is None:
            continue
        states = [state for state, allowed in state_tools.items() if name in allowed]
        lines.append(
            f"| {name} | {'あり' if 'write' in tool.tags else 'なし'} | "
            f"{'はい' if tool.idempotent else 'いいえ'} | "
            f"{'必要' if tool.requires_approval else '不要'} | "
            f"{', '.join(tool.schema.get('required', [])) or '（なし）'} | "
            f"{', '.join(states) or '（なし）'} | "
            f"{'はい' if name in MATERIAL_TOOLS else 'いいえ'} |")
    return "\n".join(lines)


def main() -> None:
    registry = build_registry()
    print("=== ツール仕様書（成果物①） ===")
    print(render_spec_md(registry))
    print()
    print("=== S04 の render_tool_spec（同じ宣言から生成した基本版） ===")
    print(render_tool_spec(registry))
    print()
    print("=== 各ツールの説明文の長さ（近似トークン数（比較用）＝文字数÷3） ===")
    print("ツール | 説明文の文字数 | 近似トークン")
    for name in registry.names():
        tool = registry.get(name)
        if tool is not None:
            print(f"{name} | {len(tool.description)} | {len(tool.description) // 3}")


if __name__ == "__main__":
    main()

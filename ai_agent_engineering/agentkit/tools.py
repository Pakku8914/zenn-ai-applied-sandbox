"""ツールの定義と呼び出し（セッション4の主題）。

例外は必ず ToolResult(ok=False) に変換する。エージェントに例外を投げ返すと
ループが止まってしまい、モデルが回復する機会を奪うため。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from .models import ToolCall, ToolResult


class ToolError(Exception):
    """ツール側の想定内の失敗。メッセージがそのままモデルに渡る。

    メッセージは「何が悪かったか」と「次に何をすべきか」の両方を含めること。
    """


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    schema: dict
    fn: Callable[..., str]
    requires_approval: bool = False
    idempotent: bool = True
    tags: tuple[str, ...] = field(default_factory=tuple)  # 権限の絞り込みに使う


class ToolRegistry:
    def __init__(self, tools: list[Tool] | None = None) -> None:
        self._tools: dict[str, Tool] = {}
        for t in tools or []:
            self.register(t)

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"ツール名が重複しています: {tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def names(self) -> list[str]:
        return sorted(self._tools)

    def subset(self, names: list[str]) -> "ToolRegistry":
        """許可リスト方式で使えるツールを絞る（セッション12の最小権限）。"""
        missing = [n for n in names if n not in self._tools]
        if missing:
            raise ValueError(f"未登録のツールを指定しています: {missing}")
        return ToolRegistry([self._tools[n] for n in names])

    def specs(self) -> list[dict]:
        """LLM に渡すツール定義。"""
        return [{"name": t.name, "description": t.description, "input_schema": t.schema}
                for t in self._tools.values()]

    def call(self, call: ToolCall) -> ToolResult:
        tool = self._tools.get(call.name)
        if tool is None:
            # 存在しないツールを呼ばれたときも例外にしない。使えるツール名を教える
            return ToolResult(call.call_id, False, "",
                              f"ツール '{call.name}' は存在しません。"
                              f"使えるツール: {', '.join(self.names())}")
        try:
            content = tool.fn(**call.args)
        except ToolError as exc:
            return ToolResult(call.call_id, False, "", str(exc))
        except TypeError as exc:
            # 引数の不一致。スキーマと実装のずれはモデルには直せないので明示する
            return ToolResult(call.call_id, False, "", f"引数が不正です: {exc}")
        except Exception as exc:  # noqa: BLE001
            # 想定外の失敗。例外の型名までは出すが、スタックトレースは渡さない
            return ToolResult(call.call_id, False, "", f"内部エラー（{type(exc).__name__}）")
        return ToolResult(call.call_id, True, str(content))

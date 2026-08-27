"""差し替え可能な LLM（オラクル）。

エージェントの教材で最も重要な要件は「同じ入力で毎回同じ軌跡になること」である。
実 API を直接呼ぶと軌跡が毎回変わり、何を直したのか分からなくなる。
そこで LLM を差し替え可能なオラクルとして扱い、既定はシナリオ再生にする。
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Protocol

from .models import LLMResponse, ToolCall

SCENARIO_DIR = Path(__file__).resolve().parent.parent / "scenarios"
FIXTURE_DIR = Path(__file__).resolve().parent.parent / "fixtures"


class LLMClient(Protocol):
    def respond(self, messages: list[dict], tools: list[dict]) -> LLMResponse: ...


def prompt_key(messages: list[dict], tools: list[dict]) -> str:
    """メッセージとツール定義から決定的なキーを作る。"""
    blob = json.dumps({"m": messages, "t": tools}, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


class ScriptedClient:
    """シナリオに書かれた応答を順に返す。本書の既定。

    シナリオの形（scenarios/*.json）:
      {"name": "...", "turns": [
         {"thought": "...", "calls": [{"name": "search_docs", "args": {...}}]},
         {"thought": "...", "final": "回答"}
      ]}
    """

    def __init__(self, scenario: str | dict) -> None:
        if isinstance(scenario, str):
            path = SCENARIO_DIR / f"{scenario}.json"
            if not path.exists():
                raise FileNotFoundError(f"{path} がありません。")
            scenario = json.loads(path.read_text(encoding="utf-8"))
        self.name: str = scenario.get("name", "unnamed")
        self.turns: list[dict] = scenario["turns"]
        self.cursor = 0

    def respond(self, messages: list[dict], tools: list[dict]) -> LLMResponse:
        if self.cursor >= len(self.turns):
            # シナリオが尽きた＝ループが想定より長く回っている。黙って終わらせない
            raise IndexError(
                f"シナリオ '{self.name}' の応答が {len(self.turns)} 個で尽きました。"
                "ループが想定より長く回っています（停止条件を確認してください）。"
            )
        turn = self.turns[self.cursor]
        self.cursor += 1
        calls = [
            ToolCall(call_id=f"{self.name}-{self.cursor}-{i}", name=c["name"], args=c.get("args", {}))
            for i, c in enumerate(turn.get("calls", []))
        ]
        # トークン数は決定的な近似値（実測ではないので本文で「実測」と呼ばない）
        approx_in = sum(len(json.dumps(m, ensure_ascii=False)) for m in messages) // 3
        return LLMResponse(
            thought=turn.get("thought", ""), calls=calls, final=turn.get("final"),
            input_tokens=approx_in,
            output_tokens=(len(turn.get("final") or "") + len(turn.get("thought", ""))) // 3,
            source="scripted",
        )


class FixtureClient:
    """プロンプトのハッシュをキーに合成カセットを再生する。"""

    def __init__(self, name: str = "turns_v1") -> None:
        path = FIXTURE_DIR / f"{name}.json"
        if not path.exists():
            raise FileNotFoundError(
                f"{path} がありません。先に `python tools/make_fixtures.py` を実行してください。"
            )
        self.data: dict[str, dict] = json.loads(path.read_text(encoding="utf-8"))
        self.name = name

    def respond(self, messages: list[dict], tools: list[dict]) -> LLMResponse:
        key = prompt_key(messages, tools)
        if key not in self.data:
            raise KeyError(
                f"カセット {self.name} に key={key} がありません。"
                "プロンプトを変えたらカセットを作り直してください。"
            )
        row = self.data[key]
        return LLMResponse(
            thought=row.get("thought", ""),
            calls=[ToolCall(f"fx-{key}-{i}", c["name"], c.get("args", {}))
                   for i, c in enumerate(row.get("calls", []))],
            final=row.get("final"),
            input_tokens=row.get("input_tokens", 0), output_tokens=row.get("output_tokens", 0),
            source="fixture",
        )


class FlakyClient:
    """任意のクライアントを包み、指定回の呼び出しで失敗を注入する（セッション11の主役）。

    fail_on: 何回目の呼び出しで失敗させるか（1始まり）
    mode: "exception"（例外）/ "empty"（何も返さない）/ "repeat"（同じツールを繰り返す）
    """

    def __init__(self, inner, fail_on: tuple[int, ...] = (2,), mode: str = "exception") -> None:
        self.inner = inner
        self.fail_on = set(fail_on)
        self.mode = mode
        self.count = 0

    def respond(self, messages: list[dict], tools: list[dict]) -> LLMResponse:
        self.count += 1
        if self.count in self.fail_on:
            if self.mode == "exception":
                raise RuntimeError(f"一時的な障害（{self.count} 回目の呼び出し）")
            if self.mode == "empty":
                return LLMResponse(thought="", calls=[], final=None, source="flaky")
            if self.mode == "repeat":
                prev = self.inner.turns[max(self.inner.cursor - 1, 0)] if hasattr(self.inner, "turns") else {}
                calls = [ToolCall(f"repeat-{self.count}-{i}", c["name"], c.get("args", {}))
                         for i, c in enumerate(prev.get("calls", []))]
                return LLMResponse(thought="（同じ操作を繰り返す）", calls=calls, source="flaky")
            raise ValueError(f"unknown mode: {self.mode}")
        return self.inner.respond(messages, tools)


class AnthropicClient:
    """実 API を呼ぶ実装。`--live` を付けた任意課題のみで使う（課金あり）。"""

    def __init__(self, model: str | None = None, max_tokens: int = 2048) -> None:
        import anthropic

        key = os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise RuntimeError("ANTHROPIC_API_KEY が未設定です。本書の必須演習に実 API は不要です。")
        self.client = anthropic.Anthropic(api_key=key)
        # モデルIDは付録の早見表を参照して指定する（本文にハードコードしない）
        self.model = model or os.environ.get("ANTHROPIC_MODEL", "")
        if not self.model:
            raise RuntimeError("ANTHROPIC_MODEL を指定してください（付録の早見表を参照）。")
        self.max_tokens = max_tokens

    def respond(self, messages: list[dict], tools: list[dict]) -> LLMResponse:
        res = self.client.messages.create(
            model=self.model, max_tokens=self.max_tokens, messages=messages, tools=tools,
        )
        thought = "".join(b.text for b in res.content if getattr(b, "type", "") == "text")
        calls = [ToolCall(b.id, b.name, dict(b.input))
                 for b in res.content if getattr(b, "type", "") == "tool_use"]
        return LLMResponse(
            thought=thought, calls=calls,
            final=None if calls else thought,
            input_tokens=res.usage.input_tokens, output_tokens=res.usage.output_tokens,
            source="api",
        )

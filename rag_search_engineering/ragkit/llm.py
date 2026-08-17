"""生成側の LLM クライアント（セッション11・12で使う）。

読者に課金を要求しないため、既定は合成カセットの再生（FixtureClient）である。
実 API を使うのは `--live` を付けた任意課題のみ。
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Protocol

from .models import LLMResponse

FIXTURE_DIR = Path(__file__).resolve().parent.parent / "fixtures"


class LLMClient(Protocol):
    def complete(self, system: str, user: str, max_tokens: int = 1024) -> LLMResponse: ...


def cache_key(system: str, user: str) -> str:
    """system と user の組から決定的なキーを作る。カセットの索引に使う。"""
    return hashlib.sha256(f"{system}\x00{user}".encode()).hexdigest()[:16]


class StubClient:
    """入力に含まれるキーワードで分岐する決定的な応答。ロジックの単体テスト用。"""

    def __init__(self, rules: dict[str, str] | None = None, default: str = "（該当情報なし）") -> None:
        self.rules = rules or {}
        self.default = default

    def complete(self, system: str, user: str, max_tokens: int = 1024) -> LLMResponse:
        for needle, answer in self.rules.items():
            if needle in user:
                return LLMResponse(text=answer, input_tokens=len(user) // 3,
                                   output_tokens=len(answer) // 3, source="stub")
        return LLMResponse(text=self.default, input_tokens=len(user) // 3,
                           output_tokens=len(self.default) // 3, source="stub")


class FixtureClient:
    """合成カセットを再生する。

    カセットは tools/make_fixtures.py が固定シードで生成した合成データであり、
    実 API の記録ではない（本文でも「合成カセット」と呼ぶ）。

    登録外の入力では例外を投げる。カセット管理のコストを実感させるための設計。
    """

    def __init__(self, name: str = "answers_v1") -> None:
        path = FIXTURE_DIR / f"{name}.json"
        if not path.exists():
            raise FileNotFoundError(
                f"{path} がありません。先に `python tools/make_fixtures.py` を実行してください。"
            )
        self.data: dict[str, dict] = json.loads(path.read_text(encoding="utf-8"))
        self.name = name

    def complete(self, system: str, user: str, max_tokens: int = 1024) -> LLMResponse:
        key = cache_key(system, user)
        if key not in self.data:
            raise KeyError(
                f"カセット {self.name} に key={key} がありません。"
                "プロンプトを変えたらカセットを作り直してください（tools/make_fixtures.py）。"
            )
        row = self.data[key]
        return LLMResponse(text=row["text"], input_tokens=row.get("input_tokens", 0),
                           output_tokens=row.get("output_tokens", 0), source="fixture")


class AnthropicClient:
    """実 API を呼ぶ実装。`--live` を付けた任意課題のみで使う（課金あり）。"""

    def __init__(self, model: str | None = None) -> None:
        import anthropic

        key = os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY が未設定です。本書の必須演習に実 API は不要です。"
            )
        self.client = anthropic.Anthropic(api_key=key)
        # モデルIDは付録の早見表を参照して指定する（本文にハードコードしない）
        self.model = model or os.environ.get("ANTHROPIC_MODEL", "")
        if not self.model:
            raise RuntimeError("ANTHROPIC_MODEL を指定してください（付録の早見表を参照）。")

    def complete(self, system: str, user: str, max_tokens: int = 1024) -> LLMResponse:
        res = self.client.messages.create(
            model=self.model, max_tokens=max_tokens, system=system,
            messages=[{"role": "user", "content": user}],
        )
        text = "".join(b.text for b in res.content if getattr(b, "type", "") == "text")
        return LLMResponse(text=text, input_tokens=res.usage.input_tokens,
                           output_tokens=res.usage.output_tokens, source="api")


def default_client(live: bool = False) -> LLMClient:
    """既定は合成カセット。--live のときだけ実 API を使う。"""
    return AnthropicClient() if live else FixtureClient()

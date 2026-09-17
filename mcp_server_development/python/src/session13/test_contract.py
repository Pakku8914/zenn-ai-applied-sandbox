"""契約テスト（Python 版）

  docker compose exec python python -m pytest src/session13 -q

TypeScript 版と「同じ入力・同じ出力テキスト」になることを確かめます。
異常系は、失敗の表現形式（isError か例外か）に依存しない形で書きます。
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest
from mcp import Client

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fixture_server import create_fixture_server  # noqa: E402
from harness import call_expecting_failure  # noqa: E402


@pytest.mark.asyncio
async def test_echo_returns_the_same_text_as_typescript() -> None:
    async with Client(create_fixture_server()) as client:
        result = await client.call_tool("echo_text", {"text": "こんにちは", "count": 2})

    # TypeScript 版のテストと同じ期待値を書く（2 言語で振る舞いが一致していることの担保）
    assert getattr(result.content[0], "text", None) == "こんにちは\nこんにちは"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("label", "arguments"),
    [
        ("必須引数が無い", {}),
        ("型が違う", {"text": 123}),
        ("上限を超える", {"text": "あ", "count": 99}),
    ],
)
async def test_invalid_arguments_fail(label: str, arguments: dict[str, Any]) -> None:
    async with Client(create_fixture_server()) as client:
        message = await call_expecting_failure(client, "echo_text", arguments)

    # 文面は SDK の版で変わりうるので、「失敗として届くこと」だけを固定する。
    # 文面に依存したテストは、直す価値のない理由で赤くなる（mid01 の RejectReason と同じ考え方）
    assert message != "", f"{label}: 失敗の説明が空でした"


@pytest.mark.asyncio
async def test_unknown_tool_fails() -> None:
    async with Client(create_fixture_server()) as client:
        message = await call_expecting_failure(client, "no_such_tool", {})

    assert "no_such_tool" in message

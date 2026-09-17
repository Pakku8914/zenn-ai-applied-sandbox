"""スキーマの回帰テスト（Python 版）

  docker compose exec python python -m pytest src/session13 -q

非同期テストには @pytest.mark.asyncio が必要です（pytest.ini は strict モード）。

pytest.ini の pythonpath は src なので、同じディレクトリのモジュールを import できるように
sys.path を足しています（章ごとにディレクトリを分けているため）。
実務ではパッケージとして構成し、相対 import で解決します（セッション14）。
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest
from mcp import Client

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fixture_server import create_fixture_server  # noqa: E402
from harness import compare_baseline  # noqa: E402
from schema_digest import digest_tools  # noqa: E402

#: TypeScript 版（schema-snapshot.test.ts）と同じ形の期待値。
#: 「同じ契約であること」を、同じ期待値を 2 か所に書くことで担保する。
EXPECTED_DIGEST: list[dict[str, Any]] = [
    {
        "name": "echo_text",
        "title": "テキストのエコー",
        "annotations": {
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
        "args": [
            {"name": "count", "required": False, "hasDescription": True},
            {"name": "text", "required": True, "hasDescription": True},
        ],
    }
]


async def _list_tools() -> Any:
    async with Client(create_fixture_server()) as client:
        return await client.list_tools()


@pytest.mark.asyncio
async def test_digest_matches_the_declared_contract() -> None:
    result = await _list_tools()
    assert digest_tools(result.tools) == EXPECTED_DIGEST


@pytest.mark.asyncio
async def test_tools_list_matches_baseline() -> None:
    result = await _list_tools()
    payload = result.model_dump(mode="json", by_alias=True, exclude_none=True)
    compare_baseline("fixture-tools-list", payload)


@pytest.mark.asyncio
async def test_python_specific_differences() -> None:
    """TypeScript とは一致しない点を、あえてテストで固定しておく。

    ここが落ちたら「Python SDK の出力が変わった」という合図になる。
    """
    tool = (await _list_tools()).tools[0]

    # ① 宣言していないのに outputSchema が自動生成される（TypeScript は宣言しないと付かない）
    assert tool.output_schema is not None
    # ② inputSchema に $schema が付かない（TypeScript は draft-07 を付ける）
    assert "$schema" not in (tool.input_schema or {})
    # ③ 各プロパティに title が付く（TypeScript は付かない）
    assert all("title" in prop for prop in (tool.input_schema or {})["properties"].values())

"""中間プロジェクト1 の契約テスト（Python 版 / 問題4-c の解答）

  docker compose exec python python -m pytest src/session13 -q

TypeScript 版と「同じダイジェスト」になることを固定します。
生の tools/list は 2 言語で一致しませんが、正規化したダイジェストは一致します。

python/src/mid01/ が無い環境ではモジュールごとスキップします（既存のテスト実行を壊さないため）。
★ ただし CI では「スキップされたこと」を成功と読み替えないでください。前提は CI で必ず用意します。
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

HERE = Path(__file__).resolve().parent
MID01 = HERE.parent / "mid01"

if not (MID01 / "create_server.py").exists():
    pytest.skip(
        "中間プロジェクト1 の Python 実装（python/src/mid01/create_server.py）が必要です",
        allow_module_level=True,
    )

sys.path.insert(0, str(HERE))
sys.path.insert(0, str(MID01))

from mcp import Client  # noqa: E402
from schema_digest import digest_tools  # noqa: E402


def _load_module(name: str, path: Path) -> Any:
    """ファイルパスを指定してモジュールを読み込む。

    create_server.py は章ごとに存在します。`from create_server import ...` と
    書くと、スイート全体を pytest で回したときに先に読み込まれた別の章のもの
    （アルファベット順で src/final/create_server.py が先）が sys.modules から
    返り、ImportError になります。名前ではなくパスで指定して衝突を避けます。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


create_docsearch_server = _load_module(
    "mid01_create_server", MID01 / "create_server.py"
).create_docsearch_server

DOCS_ROOT = Path("src/mid01/docs").resolve()

#: TypeScript 版（schema-snapshot.test.ts の SEARCH_TOOL_DIGEST）と同じ内容。
#: 片方だけ直すと片方が落ちる ―― これが「2 言語で契約が一致している」ことの担保。
EXPECTED_DIGEST: list[dict[str, Any]] = [
    {
        "name": "search_documents",
        "title": "社内ドキュメントの全文検索",
        "annotations": {
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
        "args": [
            {"name": "directory", "required": False, "hasDescription": True},
            {"name": "limit", "required": False, "hasDescription": True},
            {"name": "query", "required": True, "hasDescription": True},
        ],
    }
]


@pytest.mark.asyncio
async def test_digest_matches_the_typescript_contract() -> None:
    async with Client(create_docsearch_server(DOCS_ROOT)) as client:
        tools = (await client.list_tools()).tools

    assert digest_tools(tools) == EXPECTED_DIGEST


@pytest.mark.asyncio
async def test_search_returns_the_same_order_as_typescript() -> None:
    async with Client(create_docsearch_server(DOCS_ROOT)) as client:
        result = await client.call_tool("search_documents", {"query": "VPN"})

    structured = result.structured_content or {}
    assert structured["totalMatched"] == 4
    # スコア降順 → パス昇順。TypeScript 版のテストと同じ期待値
    assert [hit["path"] for hit in structured["results"]] == [
        "guides/vpn-setup.md",
        "remote-work.md",
        "onboarding.md",
        "security-policy.md",
    ]

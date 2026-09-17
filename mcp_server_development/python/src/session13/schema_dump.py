"""tools/list を書き出す（Python 版）

  docker compose exec python python src/session13/schema_dump.py
  docker compose exec python python src/session13/schema_dump.py --write

クライアント側のスクリプトなので print() を使ってかまいません。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import anyio

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fixture_server import create_fixture_server  # noqa: E402
from harness import SNAPSHOT_DIR  # noqa: E402
from mcp import Client  # noqa: E402


async def main() -> None:
    async with Client(create_fixture_server()) as client:
        result = await client.list_tools()

    # by_alias=True で「電文と同じ camelCase」に戻す（属性は snake_case なので）
    payload = result.model_dump(mode="json", by_alias=True, exclude_none=True)
    serialized = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    print(serialized)

    if "--write" in sys.argv:
        SNAPSHOT_DIR.mkdir(exist_ok=True)
        file = SNAPSHOT_DIR / "fixture-tools-list.json"
        file.write_text(serialized, encoding="utf-8")
        print(f"書き出しました: {file}")


if __name__ == "__main__":
    anyio.run(main)

"""横断復習1 問題7 ― 2 言語の tools/list を「契約」の観点だけで照合する

手順:
  1. TypeScript 版の tools/list を保存する（sandbox ディレクトリで実行）
     docker compose exec -T node npx mcp-inspector --cli npx tsx src/review01/server.ts \
       --method tools/list > python/src/review01/tools-ts.json
  2. 照合する
     docker compose exec python python src/review01/q7_contract_check.py

このスクリプトはクライアント側なので print を使ってかまいません
（通信路として stdout を使うのはサーバープロセスのほうだけです）。
"""

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

TS_TOOLS_PATH = Path(__file__).with_name("tools-ts.json")
PY_ENTRY = "src/review01/q4_server.py"

# 引数スキーマから落とす「表現差」のキー
# title: Pydantic が Python の引数名から自動生成する / default: 任意引数に付く null
IGNORED_PROPERTY_KEYS = frozenset({"title", "default"})


def normalize_property(schema: dict[str, Any]) -> dict[str, Any]:
    """任意引数の anyOf を畳み、表現差のキーを落とす"""
    merged = dict(schema)
    branches = merged.pop("anyOf", None)
    if isinstance(branches, list):
        real = [branch for branch in branches if branch.get("type") != "null"]
        if len(real) == 1:
            # 外側にあった description などを内側の分岐に引き継ぐ
            merged = {**real[0], **merged}
    return {key: value for key, value in merged.items() if key not in IGNORED_PROPERTY_KEYS}


def normalize_tool(tool: dict[str, Any]) -> dict[str, Any]:
    """ツール定義を「クライアントから見た契約」だけに絞る。

    落としているもの: inputSchema の $schema / title、ツールの execution など
    残しているもの:   title / description / required / 引数のスキーマ
    """
    schema = tool.get("inputSchema", {})
    properties = {
        name: normalize_property(prop) for name, prop in schema.get("properties", {}).items()
    }
    return {
        "title": tool.get("title"),
        "description": tool.get("description"),
        "required": sorted(schema.get("required", [])),
        "properties": properties,
    }


def normalize_list(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {tool["name"]: normalize_tool(tool) for tool in payload.get("tools", [])}


async def fetch_python_tools() -> dict[str, Any]:
    """Python 版サーバーを子プロセスとして起動し、tools/list を電文どおりのキー名で取る"""
    params = StdioServerParameters(command="python", args=[PY_ENTRY])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.list_tools()
    # by_alias=True を忘れると input_schema のような snake_case のキーになり比較できない
    return result.model_dump(mode="json", by_alias=True, exclude_none=True)


def compare(ts: dict[str, Any], py: dict[str, Any]) -> int:
    """一致していれば 0、していなければ 1 を返す"""
    ts_names, py_names = set(ts), set(py)
    ok = True

    # ① 集合の差（片方にしか無いツール）
    if ts_names == py_names:
        print(f"[PASS] ツール名の集合: {', '.join(sorted(ts_names))}")
    else:
        ok = False
        print("[FAIL] ツール名の集合が違います")
        print(f"       TypeScript 版だけにある: {sorted(ts_names - py_names) or 'なし'}")
        print(f"       Python 版だけにある:     {sorted(py_names - ts_names) or 'なし'}")

    # ② 値の差（両方にあるツールの中身）
    matched = 0
    for name in sorted(ts_names & py_names):
        left, right = ts[name], py[name]
        if left == right:
            matched += 1
            print(f"[PASS] {name}")
            continue

        ok = False
        print(f"[FAIL] {name}")
        for key in ("title", "description", "required"):
            if left[key] != right[key]:
                print(f"       {key}: TS={left[key]!r} / PY={right[key]!r}")
        for prop in sorted(set(left["properties"]) | set(right["properties"])):
            left_prop = left["properties"].get(prop)
            right_prop = right["properties"].get(prop)
            if left_prop != right_prop:
                print(f"       properties.{prop}: TS={left_prop!r} / PY={right_prop!r}")

    total = len(ts_names | py_names)
    print(
        f"{matched}/{total} ツールが契約一致"
        "（無視した表現差: 引数の title / default / $schema / スキーマの title / execution）"
    )
    return 0 if ok else 1


def main() -> None:
    if not TS_TOOLS_PATH.exists():
        print(f"{TS_TOOLS_PATH} がありません。先に次を実行してください:", file=sys.stderr)
        print(
            "docker compose exec -T node npx mcp-inspector --cli "
            "npx tsx src/review01/server.ts --method tools/list "
            "> python/src/review01/tools-ts.json",
            file=sys.stderr,
        )
        sys.exit(1)

    ts = normalize_list(json.loads(TS_TOOLS_PATH.read_text(encoding="utf-8")))
    py = normalize_list(asyncio.run(fetch_python_tools()))

    print(f"== 契約チェック: {TS_TOOLS_PATH.name} vs {PY_ENTRY} ==")
    sys.exit(compare(ts, py))


if __name__ == "__main__":
    main()

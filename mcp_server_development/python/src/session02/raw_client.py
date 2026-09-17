"""SDK を使わずに素の JSON-RPC 電文でサーバーを動かすクライアント（Python）

MCP の SDK は一切 import しません。標準ライブラリの subprocess で src/server.py を
子プロセスとして起動し、標準入力へ JSON を 1 行ずつ書き込み、標準出力から返ってきた
行をそのまま表示します。

これはクライアント側のスクリプトなので print() を使ってかまいません。
標準出力が通信路になるのはサーバー側のプロセスだけです。

実行: docker compose exec python python src/session02/raw_client.py
"""

from __future__ import annotations

import json
import subprocess
import sys
from typing import Any

# protocol_versions.py で確認した値に合わせてください
PROTOCOL_VERSION = "2025-11-25"


def send(proc: subprocess.Popen[str], message: dict[str, Any]) -> None:
    """1 行の JSON としてサーバーの標準入力へ書き込む（改行が電文の区切り）"""
    line = json.dumps(message, ensure_ascii=False, separators=(",", ":"))
    print(f"C->S {line}")
    stdin = proc.stdin
    assert stdin is not None
    stdin.write(line + "\n")
    stdin.flush()  # 行バッファを明示的に押し出す。忘れると相手に届かない


def receive(proc: subprocess.Popen[str]) -> dict[str, Any]:
    """サーバーの標準出力から 1 行読み、JSON として解釈する"""
    stdout = proc.stdout
    assert stdout is not None
    line = stdout.readline()
    if line == "":
        raise RuntimeError("サーバーが応答を返さずに終了しました")
    print(f"S->C {line.rstrip()}")
    return json.loads(line)


def main() -> None:
    proc = subprocess.Popen(
        [sys.executable, "src/server.py"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        # stderr は指定しない = このプロセスの stderr をそのまま引き継ぐ
        text=True,
        encoding="utf-8",
        bufsize=1,
    )

    try:
        # ① initialize（リクエスト。応答を待つ）
        send(
            proc,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": "raw-client", "version": "1.0.0"},
                },
            },
        )
        init = receive(proc)["result"]
        print(f"    合意したバージョン: {init['protocolVersion']}")
        print(f"    サーバーのケイパビリティ: {json.dumps(init['capabilities'])}")

        # ② notifications/initialized（通知。id が無く、応答も返らない）
        send(proc, {"jsonrpc": "2.0", "method": "notifications/initialized"})
        print("    ↑ 通知なので応答は待たない（ここで readline すると永久に止まる）")

        # ③ tools/list
        send(proc, {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        tools = receive(proc)["result"]["tools"]
        print(f"    公開されているツール: {[tool['name'] for tool in tools]}")

        # ④ tools/call
        send(
            proc,
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "add", "arguments": {"a": 2, "b": 3}},
            },
        )
        content = receive(proc)["result"]["content"]
        print(f"    content[0]: {content[0]}")

        # ⑤ 存在しないメソッド（エラー応答を観察する）
        send(proc, {"jsonrpc": "2.0", "id": 4, "method": "tools/nonexistent", "params": {}})
        print(f"    error: {receive(proc).get('error')}")
    finally:
        stdin = proc.stdin
        assert stdin is not None
        stdin.close()  # 標準入力を閉じるとサーバーは終了する
        proc.wait(timeout=10)


if __name__ == "__main__":
    main()

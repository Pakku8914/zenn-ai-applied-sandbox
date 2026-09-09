#!/usr/bin/env python3
"""セッション8: MCP サーバーを別プロセスとして起動し、stdio で話すクライアント。

MCP サーバーは「別のプロセス」です。ライブラリを import するのとは違い、
**起動・タイムアウト・後片付け**を自分で面倒みる必要があります。
このファイルはその3点に集中しています。

    with MCPClient() as client:          # 起動 → initialize → 終了時に必ず片付け
        tools = client.list_tools()
        result = client.call_tool("search_internal_docs", {"query": "有給休暇 繰越 上限"})

読み取りは `select` + `os.read` で行い、**必ずタイムアウトを持たせます**。
`readline()` をそのまま呼ぶと、サーバーが黙り込んだ瞬間にエージェントが永久に固まります。
"""

from __future__ import annotations

import json
import os
import select
import subprocess
import sys
import time
from pathlib import Path

SERVER_SCRIPT = str(Path(__file__).resolve().parent / "mcp_server.py")
DEFAULT_TIMEOUT = 10.0
PROTOCOL_VERSION = "2025-06-18"
CLIENT_INFO = {"name": "helpdesk-orchestrator", "version": "1.0.0"}


class MCPError(RuntimeError):
    """MCP 接続に関する失敗の基底クラス。"""


class MCPTimeout(MCPError):
    """時間内に応答が来なかった。"""


class MCPDesynced(MCPError):
    """応答を取りこぼしたため、この接続はもう信用できない。"""


class MCPProtocolError(MCPError):
    """応答の形が約束と違う（id 不一致・JSON でない・プロセス終了）。"""


class MCPRpcError(MCPError):
    """サーバーが JSON-RPC の error を返した（＝呼び出し側のバグ）。"""

    def __init__(self, code: int, message: str, data=None) -> None:
        super().__init__(f"JSON-RPC error {code}: {message}")
        self.code = code
        self.rpc_message = message
        self.data = data


class MCPClient:
    """stdio の MCP サーバーを1つ抱えるクライアント。"""

    def __init__(self, script: str = SERVER_SCRIPT, *, python: str | None = None) -> None:
        self.script = script
        self.python = python or sys.executable
        self.server_info: dict | None = None
        self.desynced = False
        self._proc: subprocess.Popen | None = None
        self._buffer = b""
        self._next_id = 0

    # -- 起動と後片付け ---------------------------------------------------

    def start(self, *, initialize: bool = True) -> dict | None:
        if self._proc is not None:
            raise MCPError("すでに起動しています。restart() を使ってください。")
        self._proc = subprocess.Popen(  # noqa: S603 — 起動するのは同梱の自作サーバー
            [self.python, self.script],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            # 標準エラー出力は親に流す（サーバーの例外を見えるようにする）
            bufsize=0,
            cwd="/workspace",
            env=os.environ.copy(),
        )
        self._buffer = b""
        self._next_id = 0
        self.desynced = False
        return self.initialize() if initialize else None

    def close(self) -> None:
        """**必ず呼ぶ。** 呼ばないとサーバーのプロセスが残り続けます。"""
        proc = self._proc
        self._proc = None
        self._buffer = b""
        self.desynced = False
        if proc is None:
            return
        try:
            if proc.poll() is None:
                try:
                    # まず標準入力を閉じて EOF を伝える（これが正常終了の合図）
                    proc.stdin.close()
                except OSError:
                    pass
                try:
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    proc.terminate()
                    try:
                        proc.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait(timeout=2)
        finally:
            for stream in (proc.stdin, proc.stdout):
                try:
                    if stream is not None:
                        stream.close()
                except OSError:
                    pass

    def restart(self) -> dict | None:
        """接続を作り直す。タイムアウトで取りこぼしたあとの唯一の復帰手段。"""
        self.close()
        return self.start()

    def __enter__(self) -> MCPClient:
        self.start()
        return self

    def __exit__(self, *_exc) -> bool:
        self.close()
        return False

    # -- 3つのメソッド ----------------------------------------------------

    def initialize(self) -> dict:
        result = self.request(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": CLIENT_INFO,
            },
        )
        self.server_info = result.get("serverInfo")
        # 初期化完了は「通知」で伝える。通知に応答は返らない
        self.notify("notifications/initialized")
        return result

    def list_tools(self, *, timeout: float = DEFAULT_TIMEOUT) -> list[dict]:
        return self.request("tools/list", timeout=timeout).get("tools", [])

    def call_tool(
        self, name: str, arguments: dict | None = None, *, timeout: float = DEFAULT_TIMEOUT
    ) -> dict:
        return self.request(
            "tools/call", {"name": name, "arguments": arguments or {}}, timeout=timeout
        )

    # -- 低レベル ---------------------------------------------------------

    def request(
        self, method: str, params: dict | None = None, *, timeout: float = DEFAULT_TIMEOUT
    ) -> dict:
        self._require_live()
        self._next_id += 1
        request_id = self._next_id
        payload: dict = {"jsonrpc": "2.0", "id": request_id, "method": method}
        if params is not None:
            payload["params"] = params
        self._send(payload)
        response = self._read_response(timeout=timeout)
        if response.get("id") != request_id:
            # 前の応答が残っている＝以後すべてズレる。ここで打ち切るのが安全
            self.desynced = True
            raise MCPProtocolError(
                f"id が一致しません（送信 {request_id} / 受信 {response.get('id')}）。"
            )
        if "error" in response:
            error = response["error"]
            raise MCPRpcError(
                error.get("code"), error.get("message", ""), error.get("data")
            )
        return response.get("result", {})

    def notify(self, method: str, params: dict | None = None) -> None:
        """id を付けずに送る。サーバーは応答してはいけない。"""
        self._require_live()
        payload: dict = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            payload["params"] = params
        self._send(payload)

    def send_raw_line(self, raw: str, *, timeout: float = DEFAULT_TIMEOUT) -> dict:
        """壊れた行をそのまま送る（パースエラーの確認用）。"""
        self._require_live()
        self._write_bytes(raw.encode("utf-8"))
        return self._read_response(timeout=timeout)

    # -- 内部 -------------------------------------------------------------

    def _require_live(self) -> None:
        if self._proc is None:
            raise MCPError("start() を呼んでください。")
        if self.desynced:
            raise MCPDesynced(
                "直前の応答を取りこぼしたため、この接続は使えません。restart() してください。"
            )
        if self._proc.poll() is not None:
            raise MCPProtocolError(
                f"サーバープロセスが終了しています（終了コード {self._proc.returncode}）。"
            )

    def _send(self, payload: dict) -> None:
        self._write_bytes((json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8"))

    def _write_bytes(self, data: bytes) -> None:
        fd = self._proc.stdin.fileno()
        while data:
            data = data[os.write(fd, data) :]

    def _read_response(self, *, timeout: float) -> dict:
        line = self._read_line(timeout=timeout)
        try:
            return json.loads(line)
        except json.JSONDecodeError as error:
            self.desynced = True
            raise MCPProtocolError(
                f"応答が JSON ではありません: {line[:200]!r}"
            ) from error

    def _read_line(self, *, timeout: float) -> bytes:
        """改行までを読む。timeout 秒で来なければ MCPTimeout。"""
        deadline = time.monotonic() + timeout
        while b"\n" not in self._buffer:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                # 応答は「あとで」届く。つまりこの接続はもう順番が合わない
                self.desynced = True
                raise MCPTimeout(f"{timeout} 秒以内に応答がありませんでした。")
            ready, _, _ = select.select([self._proc.stdout], [], [], remaining)
            if not ready:
                continue
            chunk = os.read(self._proc.stdout.fileno(), 65536)
            if not chunk:
                raise MCPProtocolError("サーバーが応答を返さずに終了しました。")
            self._buffer += chunk
        line, _, self._buffer = self._buffer.partition(b"\n")
        return line


def to_tool_config(tools: list[dict], names: list[str] | None = None) -> dict:
    """MCP のツール定義を Bedrock Converse API の `toolConfig` に変換する。

    違いはスキーマの包み方だけです（MCP は生の JSON Schema、Bedrock は `{"json": ...}`）。
    **名前・説明文・スキーマは1文字も書き換えません。** ここで書き換えると、
    MCP サーバー側の定義と食い違い、どちらが正なのか分からなくなります。

    `names` を渡すと、その道具だけを載せます。エージェントに渡す道具は
    サーバーの全ツールではなく、役割ごとに絞るのが基本です。
    """
    if names is None:
        selected = list(tools)
    else:
        by_name = {tool["name"]: tool for tool in tools}
        missing = [name for name in names if name not in by_name]
        if missing:
            raise MCPError(f"サーバーに無い道具が指定されました: {missing}")
        selected = [by_name[name] for name in names]
    return {
        "tools": [
            {
                "toolSpec": {
                    "name": tool["name"],
                    "description": tool["description"],
                    "inputSchema": {"json": tool["inputSchema"]},
                }
            }
            for tool in selected
        ]
    }

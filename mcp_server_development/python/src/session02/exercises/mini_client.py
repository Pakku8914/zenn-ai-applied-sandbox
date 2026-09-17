"""SDK を使わない最小の MCP クライアント（Python / 標準ライブラリのみ）

mcp パッケージを一切 import せず、subprocess + threading + queue だけで
MCP のハンドシェイクとツール呼び出しを行います。

要点は 3 つ:
  1. id を自動採番し、応答を id で突き合わせる（到着順に依存しない）
  2. 通知には応答を待たない（id を付けない）
  3. 応答待ちにタイムアウトを設ける（メインスレッドを永久にブロックしない）

実行: docker compose exec python python src/session02/exercises/mini_client.py
"""

from __future__ import annotations

import json
import queue
import subprocess
import sys
import threading
from typing import Any

# protocol_versions.py で確認した値に合わせてください
PROTOCOL_VERSION = "2025-11-25"
DEFAULT_TIMEOUT = 5.0


class MiniClient:
    """標準入出力で JSON-RPC をやり取りする最小クライアント"""

    def __init__(self, command: list[str]) -> None:
        self._proc = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            # stderr は指定しない = このプロセスの stderr を引き継ぐ（サーバーのログが見える）
            text=True,
            encoding="utf-8",
            bufsize=1,
        )
        # 読み取り専用スレッドが受信行を積むキュー。None は EOF の合図
        self._inbox: queue.Queue[str | None] = queue.Queue()
        # 待っていない id の応答を取り置きしておく箱（到着順が入れ替わっても壊れない）
        self._stash: dict[str, dict[str, Any]] = {}
        self._next_id = 1

        self.sent_requests = 0
        self.sent_notifications = 0
        self.received_responses = 0
        self.received_errors = 0
        self.timeouts = 0

        thread = threading.Thread(target=self._read_loop, daemon=True)
        thread.start()

    def _read_loop(self) -> None:
        """別スレッドで標準出力を読み続ける。readline にタイムアウトが無いための工夫"""
        stdout = self._proc.stdout
        assert stdout is not None
        for line in stdout:
            self._inbox.put(line)
        self._inbox.put(None)

    def _write(self, message: dict[str, Any]) -> None:
        line = json.dumps(message, ensure_ascii=False, separators=(",", ":"))
        # クライアント側なので標準出力に書いてよい（通信路はサーバーの標準入出力）
        print(f"C->S {line}")
        stdin = self._proc.stdin
        assert stdin is not None
        stdin.write(line + "\n")
        stdin.flush()  # 行バッファを明示的に押し出す。忘れると相手に届かない

    def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        """通知を送る。id を付けないので応答は待たない"""
        message: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            message["params"] = params
        self._write(message)
        self.sent_notifications += 1

    def request(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> dict[str, Any] | None:
        """リクエストを送り、同じ id の応答が返るまで待つ（タイムアウトあり）"""
        message_id = self._next_id
        self._next_id += 1
        message: dict[str, Any] = {"jsonrpc": "2.0", "id": message_id, "method": method}
        if params is not None:
            message["params"] = params
        self._write(message)
        self.sent_requests += 1
        return self._wait_for(str(message_id), timeout)

    def expect_silence(self, timeout: float) -> dict[str, Any] | None:
        """何も返らないことを確かめるための待機（通知の直後に使う）"""
        return self._wait_for(None, timeout)

    def _wait_for(self, message_id: str | None, timeout: float) -> dict[str, Any] | None:
        if message_id is not None and message_id in self._stash:
            return self._stash.pop(message_id)

        while True:
            try:
                line = self._inbox.get(timeout=timeout)
            except queue.Empty:
                self.timeouts += 1
                return None
            if line is None:  # サーバーが終了した
                self.timeouts += 1
                return None

            print(f"S->C {line.rstrip()}")
            message: dict[str, Any] = json.loads(line)
            if "error" in message:
                self.received_errors += 1
            if "result" in message or "error" in message:
                self.received_responses += 1

            received_id = message.get("id")
            if message_id is None:
                return message  # 待つ相手を決めていない場合は最初に来たものを返す
            if received_id is not None and str(received_id) == message_id:
                return message
            if received_id is not None:
                self._stash[str(received_id)] = message  # 別の id は取り置き

    def close(self) -> None:
        stdin = self._proc.stdin
        assert stdin is not None
        stdin.close()  # 標準入力を閉じるとサーバーは終了する
        self._proc.wait(timeout=10)


def main() -> None:
    client = MiniClient([sys.executable, "src/server.py"])
    try:
        init = client.request(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "mini-client", "version": "1.0.0"},
            },
        )
        assert init is not None, "initialize の応答が返りませんでした"
        print(f"    合意したバージョン: {init['result']['protocolVersion']}")

        client.notify("notifications/initialized")
        print("    通知の応答を 1 秒だけ待ってみます（返らないことの確認）")
        if client.expect_silence(1.0) is None:
            print("    → 1 秒待っても何も返りませんでした（通知には応答が無い）")
        else:
            print("    → 何か返りました。通知の理解を見直してください")

        tools = client.request("tools/list", {})
        assert tools is not None, "tools/list の応答が返りませんでした"
        print(f"    ツール: {[tool['name'] for tool in tools['result']['tools']]}")

        called = client.request(
            "tools/call", {"name": "add", "arguments": {"a": 2, "b": 3}}
        )
        assert called is not None, "tools/call の応答が返りませんでした"
        print(f"    content[0].text: {called['result']['content'][0]['text']}")

        failed = client.request("tools/nonexistent", {})
        assert failed is not None, "エラー応答が返りませんでした"
        print(f"    error: {failed['error']}")
    finally:
        client.close()

    print("\n--- 集計 ---")
    print(f"送ったリクエスト: {client.sent_requests} 件")
    print(
        f"返ってきた応答:   {client.received_responses} 件"
        f"（うちエラー {client.received_errors} 件）"
    )
    print(f"送った通知:       {client.sent_notifications} 件")
    print(f"タイムアウト:     {client.timeouts} 回（通知の応答待ち）")


if __name__ == "__main__":
    main()

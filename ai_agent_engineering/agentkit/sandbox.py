"""隔離実行（セッション9の参照実装）。

`tool-runner` コンテナはネットワーク名前空間を持たない（`network_mode: none`）ため、
HTTP で依頼を受けることができない。そこで共有ボリューム上のファイルを介して依頼する。
不便になった代わりに「外に出る経路が存在しない」という強い保証が得られる。
"""

from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path

from .models import ToolResult
from .tools import Tool, ToolError

QUEUE = Path(os.environ.get("RUNNER_QUEUE", "/workspace/runner_queue"))


def run_python(code: str, timeout: float = 10.0, memory_mb: int = 128,
               call_id: str = "run") -> ToolResult:
    """隔離コンテナで Python コードを実行する。

    戻り値の content は「標準出力（と標準エラー）」。例外は ToolResult(ok=False) にする。
    """
    QUEUE.mkdir(parents=True, exist_ok=True)
    job_id = f"{int(time.time() * 1000)}-{uuid.uuid4().hex[:8]}"
    req = QUEUE / f"{job_id}.req.json"
    res = QUEUE / f"{job_id}.res.json"

    # 一時ファイルに書いてから rename する（worker が書きかけを読まないように）
    tmp = QUEUE / f"{job_id}.tmp"
    tmp.write_text(json.dumps({"code": code, "timeout": timeout, "memory_mb": memory_mb},
                              ensure_ascii=False), encoding="utf-8")
    tmp.rename(req)

    deadline = time.time() + timeout + 10.0
    while time.time() < deadline:
        if res.exists():
            payload = json.loads(res.read_text(encoding="utf-8"))
            res.unlink(missing_ok=True)
            if payload.get("ok"):
                return ToolResult(call_id, True, payload.get("stdout", ""))
            return ToolResult(call_id, False, payload.get("stdout", ""),
                              payload.get("error", "実行に失敗しました"))
        time.sleep(0.05)

    req.unlink(missing_ok=True)
    return ToolResult(call_id, False, "",
                      "実行ワーカーから応答がありません。"
                      "`docker compose ps` で tool-runner が動いているか確認してください。")


def make_run_python_tool(timeout: float = 10.0, memory_mb: int = 128) -> Tool:
    def _fn(code: str) -> str:
        result = run_python(code, timeout=timeout, memory_mb=memory_mb)
        if not result.ok:
            raise ToolError(f"{result.error}\n（標準出力: {result.content[:200]}）")
        return result.content

    return Tool(
        name="run_python",
        description=(
            "Python コードを隔離環境で実行し、標準出力を返します。"
            "外部ネットワークには接続できません。/work 配下にのみ書き込めます。"
            "計算・集計・整形に使ってください。"
        ),
        schema={"type": "object",
                "properties": {"code": {"type": "string", "description": "実行する Python コード"}},
                "required": ["code"]},
        fn=_fn,
        idempotent=False,
        tags=("compute",),
    )

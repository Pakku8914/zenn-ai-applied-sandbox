#!/usr/bin/env python3
"""セッション8: MCP の道具でエージェントを回す。

セッション7で作ったループ（`toolConfig` → `toolUse` → `toolResult`）の
**道具の実体を MCP サーバーに置き換えた**ものです。ループ自体の作りは変わりません。
変わるのは「道具を実行する関数（executor）を差し替えられる」ことだけで、
これが承認ゲートやモック化の差し込み口になります。

    trace = run_agent(runtime, "出張の宿泊費の上限はいくらですか？",
                      tool_config=tool_config, executor=make_executor(client))

停止条件は `max_iterations` のみをここに置きます（多層の停止条件はセッション7で設計済み）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, "/workspace")
sys.path.insert(0, str(Path(__file__).resolve().parent))

import mcp_client  # noqa: E402

MODEL_ID = "amazon.nova-lite-v1:0"  # ツール利用に対応したモデル（カタログの7件から選ぶ）
MAX_ITERATIONS = 4
MAX_TOKENS = 512

SYSTEM_PROMPT = (
    "あなたはサンプル商事の社内ヘルプデスクの担当者です。"
    "社内の制度や手続きを聞かれたら、必ず道具で調べてから答えます。"
    "資料に無いことは推測せず、分からないと答えます。"
)

# --- 実験用の「悪い定義」 ---------------------------------------------------
# サーバー本体（mcp_server.py）には良い定義だけを置き、比較対象はここに置く。

VAGUE_TOOL = {
    "name": "helper",
    "description": "必要に応じて社内の情報を調べます。",
    "inputSchema": {
        "type": "object",
        "properties": {"input": {"type": "string", "description": "調べたいこと"}},
        "required": ["input"],
    },
}

# 検索と責務が重なる説明文。どちらを呼ぶべきか決められなくなる
SLOPPY_LOOKUP_DESCRIPTION = "出張や宿泊費の上限について調べるときに使います。"


def with_description(tools: list[dict], name: str, description: str) -> list[dict]:
    """説明文だけを差し替えたツール一覧を返す（実験用）。"""
    return [
        {**tool, "description": description} if tool["name"] == name else tool
        for tool in tools
    ]


# --- 引数の手当て -----------------------------------------------------------


def repair_arguments(schema: dict, arguments: dict) -> tuple[dict, list[str]]:
    """**任意引数だけ**を手当てし、必須引数には触らない。

    必須引数まで勝手に埋めると、モデルの誤りが記録に残らず原因追跡ができません。
    逆に、任意引数の些細な誤り（存在しない候補・null）でツール全体を失敗させると、
    1回の誤りで会話が終わってしまいます。

    手当てした内容は必ずモデルに返します（黙って直すと同じ誤りが繰り返されます）。
    """
    properties: dict = schema.get("properties") or {}
    required = set(schema.get("required") or [])
    fixed: dict = {}
    notes: list[str] = []
    for key, value in arguments.items():
        prop = properties.get(key)
        if prop is None:
            notes.append(f"{key} は受け付けない引数なので無視しました。")
            continue
        if value is None and key not in required:
            continue
        if "enum" in prop and key not in required and value not in prop["enum"]:
            candidates = " / ".join(str(v) for v in prop["enum"])
            notes.append(
                f"{key} の値 '{value}' は候補に無いので無視しました（候補: {candidates}）。"
            )
            continue
        fixed[key] = value
    return fixed, notes


# --- 道具の実行（差し替え可能な口） -----------------------------------------


def _error_result(message: str) -> dict:
    return {"content": [{"type": "text", "text": message}], "isError": True}


def make_executor(client: mcp_client.MCPClient, *, timeout: float = 10.0):
    """MCP クライアントを包んだ実行関数を返す。

    プロトコルの失敗（未知のツール・タイムアウト）も、**モデルが読める日本語**に
    翻訳して返します。生の `JSON-RPC error -32602` を渡してもモデルは直せません。
    """

    def execute(name: str, arguments: dict) -> dict:
        try:
            return client.call_tool(name, arguments, timeout=timeout)
        except mcp_client.MCPRpcError as error:
            return _error_result(
                f"道具 {name} は呼び出せませんでした（{error.rpc_message}）。"
                "別の道具を使うか、分からないと答えてください。"
            )
        except mcp_client.MCPTimeout:
            client.restart()  # 取りこぼした応答が残るので接続を作り直す
            return _error_result(
                f"道具 {name} は時間内に応答しませんでした。"
                "この道具は使わずに、分かる範囲で答えてください。"
            )

    return execute


# --- ツール結果をプロンプトに載せる形にする ---------------------------------


def as_context(payload_text: str) -> str:
    """検索結果を `<context>` で包む。

    プロンプトの体裁を決めるのは**オーケストレータ側**です（サーバーではない）。
    こう分けておくと、同じ MCP サーバーを別のプロンプト設計から使い回せます。
    """
    try:
        payload = json.loads(payload_text)
    except json.JSONDecodeError:
        return payload_text
    lines = [
        f'[出典 {hit["uri"]} | {hit["title"]}] {hit["text"]}'
        for hit in payload.get("hits", [])
    ]
    if not lines:
        return "<context>\n（該当する資料が見つかりませんでした）\n</context>"
    return "<context>\n" + "\n".join(lines) + "\n</context>"


def _result_text(name: str, result: dict, notes: list[str]) -> str:
    text = "\n".join(block.get("text", "") for block in result.get("content", []))
    prefix = "".join(f"[補正] {note}\n" for note in notes)
    if result.get("isError"):
        return prefix + text
    if name == "search_internal_docs":
        return prefix + as_context(text)
    return prefix + text


# --- ループ本体 -------------------------------------------------------------


def run_agent(
    runtime,
    question: str,
    *,
    tool_config: dict,
    executor,
    system: str = SYSTEM_PROMPT,
    model_id: str = MODEL_ID,
    repair: bool = True,
    max_iterations: int = MAX_ITERATIONS,
) -> dict:
    """1問に答えるまでループし、途中の記録（trace）を返す。"""
    schemas = {
        tool["toolSpec"]["name"]: tool["toolSpec"]["inputSchema"]["json"]
        for tool in tool_config["tools"]
    }
    messages: list[dict] = [{"role": "user", "content": [{"text": question}]}]
    trace: dict = {
        "question": question,
        "exposed_tools": sorted(schemas),
        "tool_calls": [],
        "model_calls": 0,
        "answer": "",
        "stop_reason": "",
    }

    for _ in range(max_iterations):
        response = runtime.converse(
            modelId=model_id,
            system=[{"text": system}],
            messages=messages,
            toolConfig=tool_config,
            inferenceConfig={"maxTokens": MAX_TOKENS, "temperature": 0.0},
        )
        trace["model_calls"] += 1
        trace["stop_reason"] = response["stopReason"]
        blocks = response["output"]["message"]["content"]
        # assistant の応答は toolUse ブロックを含めてそのまま履歴に戻す
        messages.append({"role": "assistant", "content": blocks})

        uses = [block["toolUse"] for block in blocks if "toolUse" in block]
        if not uses:
            trace["answer"] = "".join(block.get("text", "") for block in blocks)
            return trace

        results: list[dict] = []
        for use in uses:
            name = use["name"]
            arguments = use.get("input") or {}
            notes: list[str] = []
            if repair:
                arguments, notes = repair_arguments(schemas.get(name, {}), arguments)
            result = executor(name, arguments)
            is_error = bool(result.get("isError"))
            trace["tool_calls"].append(
                {
                    "name": name,
                    "input": arguments,
                    "is_error": is_error,
                    "notes": notes,
                }
            )
            results.append(
                {
                    "toolResult": {
                        "toolUseId": use["toolUseId"],
                        "content": [{"text": _result_text(name, result, notes)}],
                        # 実 Bedrock はこの status を見る。エラーを success で返さない
                        "status": "error" if is_error else "success",
                    }
                }
            )
        messages.append({"role": "user", "content": results})

    trace["stop_reason"] = "max_iterations"
    return trace

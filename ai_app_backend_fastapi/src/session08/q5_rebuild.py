"""練習問題5の解答：受け取った SSE のイベント列（API契約③）から、Anthropic 形式の発言を組み立て直す。"""

from __future__ import annotations

import json


def rebuild_messages(events: list[dict]) -> list[dict]:
    """events は sse_events() の形（{"event", "data", ...}）。増えた発言（assistant と tool_result の user）を返す。"""
    out: list[dict] = []
    text: list[str] = []

    def assistant() -> dict:
        # tool_result の後に来た delta・tool_call は、次のステップ（新しい assistant の発言）の始まり
        if not out or out[-1]["role"] != "assistant":
            out.append({"role": "assistant", "content": []})
        return out[-1]

    def flush_text() -> None:
        if text:
            assistant()["content"].insert(0, {"type": "text", "text": "".join(text)})  # テキストは先頭に置く
            text.clear()

    for ev in events:
        name, data = ev["event"], ev["data"]
        if name == "delta":
            assistant()
            text.append(data["text"])
        elif name == "tool_call":
            assistant()["content"].append({"type": "tool_use", "id": data["id"], "name": data["name"],
                                           "input": data["input"]})
        elif name == "tool_result":
            flush_text()
            if out[-1]["role"] != "user":
                out.append({"role": "user", "content": []})
            output = data["output"]
            out[-1]["content"].append({
                "type": "tool_result", "tool_use_id": data["id"], "is_error": data["is_error"],
                "content": output if isinstance(output, str) else json.dumps(output, ensure_ascii=False)})
        elif name in ("done", "error"):
            flush_text()
    return out

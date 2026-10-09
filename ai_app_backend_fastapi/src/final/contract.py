"""UI Message Stream の契約テスト（受信側の検査を Python で書いたもの）。AI SDK の UI Message Stream Protocol に合わせる。

- check_ui_response：ステータス・ヘッダ5個・`data:` 行だけ・[DONE] で終わる・チャンクの並びの規則
- shape：同じ種類の連続を1つにまとめた並び（§3.4 の参照の書き方と同じ）
- rebuild：チャンクから UIMessage の parts を組み立て直す（readUIMessageStream と同じ規則の最小版）
②の受信側（ai@7.0.127 の DefaultChatTransport）が読めるかを、①の側で先に確かめるための部品。
"""

from __future__ import annotations

import json

from .uistream import UI_STREAM_HEADERS

KNOWN_TYPES = frozenset({
    "start", "start-step", "text-start", "text-delta", "text-end", "reasoning-start", "reasoning-delta",
    "reasoning-end", "tool-input-start", "tool-input-delta", "tool-input-available", "tool-input-error",
    "tool-approval-request", "tool-approval-response", "tool-output-available", "tool-output-error",
    "tool-output-denied", "source-url", "source-document", "file", "reasoning-file", "custom", "finish-step",
    "reset-step", "message-metadata", "finish", "abort", "error"})
FINISH_REASONS = frozenset({"stop", "length", "content-filter", "tool-calls", "error", "other"})


def parse_body(text: str) -> tuple[list[dict], bool]:
    """本文を `data:` 行の JSON の列にする。[DONE] を読んだら True。SSE のコメント（: ...）は読み飛ばす。"""
    chunks: list[dict] = []
    done = False
    for block in text.split("\n\n"):
        for line in block.split("\n"):
            if not line or line.startswith(":"):
                continue
            assert line.startswith("data: "), f"data: で始まらない行があります: {line[:40]!r}"
            payload = line[len("data: "):]
            assert not done, "[DONE] のあとにチャンクがあります"
            if payload == "[DONE]":
                done = True
                continue
            chunks.append(json.loads(payload))
    return chunks, done


def check_order(chunks: list[dict]) -> None:
    """受信側がエラーにする並び（text-start の無い text-delta など）と、§3.4 の順序を検査する。"""
    assert chunks and chunks[0]["type"] in ("start", "error"), "最初のチャンクは start（開始直後の失敗は error）"
    assert chunks[-1]["type"] == "finish", "最後のチャンク（[DONE] の前）は finish"
    assert chunks[-1].get("finishReason") in FINISH_REASONS, chunks[-1]
    open_texts: set[str] = set()
    tools: dict[str, str] = {}  # toolCallId → 状態
    in_step = False
    step_tools: set[str] = set()
    for i, c in enumerate(chunks):
        kind = c["type"]
        assert kind in KNOWN_TYPES or kind.startswith("data-"), f"未知の type: {kind}"
        if kind == "start-step":
            assert not in_step, "start-step が閉じないまま次の start-step"
            in_step, step_tools = True, set()
        elif kind == "finish-step":
            assert in_step and not open_texts, "finish-step の前に text-end が来ていない"
            assert all(tools[t].startswith("output") for t in step_tools), "結果の無いツールのまま finish-step"
            in_step = False
        elif kind == "text-start":
            assert in_step, "ステップの外の text-start"
            open_texts.add(c["id"])
        elif kind == "text-delta":
            assert c["id"] in open_texts, f"text-start の無い text-delta（id={c['id']}）"
        elif kind == "text-end":
            open_texts.discard(c["id"])
        elif kind == "tool-input-start":
            tools[c["toolCallId"]] = "input-streaming"
            step_tools.add(c["toolCallId"])
        elif kind == "tool-input-delta":
            assert tools.get(c["toolCallId"]) == "input-streaming", "tool-input-start の無い tool-input-delta"
        elif kind == "tool-input-available":
            tools[c["toolCallId"]] = "input-available"
        elif kind in ("tool-output-available", "tool-output-error"):
            assert tools.get(c["toolCallId"]) == "input-available", "tool-input-available の前に結果が来た"
            tools[c["toolCallId"]] = "output-available" if kind == "tool-output-available" else "output-error"
        elif kind == "data-usage":
            assert chunks[i + 1]["type"] == "finish", "data-usage は finish の直前"
    if chunks[-1].get("finishReason") != "error":
        assert not in_step, "finish の前にステップが閉じていない"


def check_ui_response(status: int, headers: dict[str, str], text: str) -> list[dict]:
    """200・ヘッダ5個・data 行・[DONE]・並び。すべて満たせばチャンクの列を返す。"""
    assert status == 200, f"status {status}: {text[:200]}"
    got = {k: headers.get(k) for k in UI_STREAM_HEADERS}
    assert got == UI_STREAM_HEADERS, f"ヘッダが違います: {got}"
    assert text.endswith("data: [DONE]\n\n"), "本文が data: [DONE] で終わっていない"
    chunks, done = parse_body(text)
    assert done, "[DONE] がありません"
    check_order(chunks)
    return chunks


def shape(chunks: list[dict]) -> str:
    """種類の並びを、同じ種類の連続を1つにまとめて「 > 」でつなぐ（§3.4 の書き方）。"""
    out: list[str] = []
    for c in chunks:
        if not out or out[-1] != c["type"]:
            out.append(c["type"])
    return " > ".join(out)


def rebuild(chunks: list[dict]) -> list[str]:
    """チャンクから parts を組み立て直し、「種類(状態)」の列にする（readUIMessageStream の最小版）。"""
    parts: list[dict] = []
    by_text: dict[str, dict] = {}
    by_tool: dict[str, dict] = {}
    for c in chunks:
        kind = c["type"]
        if kind == "start-step":
            parts.append({"type": "step-start"})
        elif kind == "text-start":
            by_text[c["id"]] = {"type": "text", "state": "streaming"}
            parts.append(by_text[c["id"]])
        elif kind == "text-end":
            by_text[c["id"]]["state"] = "done"
        elif kind == "tool-input-start":
            by_tool[c["toolCallId"]] = {"type": f"tool-{c['toolName']}", "state": "input-streaming"}
            parts.append(by_tool[c["toolCallId"]])
        elif kind == "tool-input-available":
            by_tool[c["toolCallId"]]["state"] = "input-available"
        elif kind == "tool-output-available":
            by_tool[c["toolCallId"]]["state"] = "output-available"
        elif kind == "tool-output-error":
            by_tool[c["toolCallId"]]["state"] = "output-error"
        elif kind.startswith("data-"):
            same = next((p for p in parts if p["type"] == kind and p.get("id") == c.get("id")), None)
            if same is None:
                parts.append({"type": kind, "id": c.get("id")})
    return [p["type"] if "state" not in p else f"{p['type']}({p['state']})" for p in parts]


def first(chunks: list[dict], kind: str) -> dict:
    return next(c for c in chunks if c["type"] == kind)


def of_type(chunks: list[dict], kind: str) -> list[dict]:
    return [c for c in chunks if c["type"] == kind]

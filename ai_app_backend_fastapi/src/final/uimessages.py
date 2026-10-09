"""AI SDK の UIMessage と、Anthropic 形式の messages を行き来する（AI SDK の UI Message Stream Protocol§4）。

- to_anthropic_messages：POST /api/chat で受け取った UIMessage[] を、LLM に送る messages にする
    step-start で区切ったステップごとに、assistant（text＋tool_use）と user（tool_result）の組に戻す
- to_ui_messages：DB に保存した発言を、GET /api/conversations/{id} で返す UIMessage[] にする（逆向き）
どちらも「結果の無いツール（input-streaming・input-available）」は捨てる。tool_use だけが残ると LLM が 400 を返す。
"""

from __future__ import annotations

import json
from collections.abc import Collection, Sequence
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from .history import INTERRUPTED_NOTE, note_message

MAX_USER_CHARS = 4000
TOO_LONG_MESSAGE = "発言が長すぎて送れません。短くして送り直してください。"
DONE_STATES = frozenset({"output-available", "output-error"})


class InvalidMessages(Exception):
    """受け取った UIMessage[] を LLM に送れない。文はクライアントに返してよい固定文だけにする。"""


class UIMessageIn(BaseModel):
    """受け取る UIMessage。parts は種類が多く将来も増えるので、ここでは辞書のまま受け取って変換時に見る。"""

    model_config = ConfigDict(extra="ignore")  # metadata など、使わない項目は捨てる

    id: str = Field(min_length=1, max_length=100)
    role: Literal["system", "user", "assistant"]
    parts: list[dict] = Field(max_length=200)


class ChatIn(BaseModel):
    """DefaultChatTransport の本文 {id, messages, trigger, messageId?}。

    extra="ignore" にしている：DefaultChatTransport は transport の body オプションの値を同じ階層に混ぜて送るため、
    forbid にすると②の設定ひとつで 422 になる。混ざった値は使わずに捨てる。
    """

    model_config = ConfigDict(extra="ignore")

    id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")  # AI SDK の chatId。会話の公開 ID として使う
    messages: list[UIMessageIn] = Field(min_length=1, max_length=200)
    trigger: Literal["submit-message", "regenerate-message"]
    messageId: str | None = Field(default=None, max_length=100)


# ---------------------------------------------------------------- UIMessage → Anthropic


def tool_name(part: dict) -> str | None:
    kind = part.get("type", "")
    if kind == "dynamic-tool":
        return part.get("toolName")
    return kind[len("tool-"):] if kind.startswith("tool-") else None


def user_blocks(parts: list[dict]) -> list[dict]:
    texts: list[str] = []
    for p in parts:
        kind = p.get("type")
        if kind == "text":
            texts.append(str(p.get("text", "")))
        elif kind == "file":
            raise InvalidMessages("この API はテキストの発言だけを受け付けます（画像やファイルは送れません）。")
        # data-* などの UI 用の part は LLM に送らない
    text = "".join(texts)
    if not text.strip():
        raise InvalidMessages("空の発言は送れません。")
    return [{"type": "text", "text": text}]


def split_steps(parts: list[dict]) -> list[list[dict]]:
    steps: list[list[dict]] = [[]]
    for p in parts:
        if p.get("type") == "step-start":
            if steps[-1]:
                steps.append([])
            continue
        steps[-1].append(p)
    return [s for s in steps if s]


def step_messages(step: list[dict]) -> list[dict]:
    """1ステップを assistant（text＋tool_use）と、あれば user（tool_result）の組にする。"""
    text = "".join(str(p.get("text", "")) for p in step if p.get("type") == "text")
    uses: list[dict] = []
    results: list[dict] = []
    for p in step:
        name = tool_name(p)
        if name is None or p.get("state") not in DONE_STATES:
            continue  # 結果の無いツールは捨てる（Session 8 の「組を分断しない」）
        call_id, args = p.get("toolCallId"), p.get("input") or {}
        if not isinstance(call_id, str) or not isinstance(args, dict):
            raise InvalidMessages("ツールの記録の形式が正しくありません。")
        uses.append({"type": "tool_use", "id": call_id, "name": name, "input": args})
        if p["state"] == "output-error":
            results.append({"type": "tool_result", "tool_use_id": call_id,
                            "content": str(p.get("errorText", "")), "is_error": True})
        else:
            output = p.get("output")
            content = output if isinstance(output, str) else json.dumps(output, ensure_ascii=False)
            results.append({"type": "tool_result", "tool_use_id": call_id, "content": content, "is_error": False})
    blocks = ([{"type": "text", "text": text}] if text else []) + uses
    if not blocks:
        return []
    out = [{"role": "assistant", "content": blocks}]
    if results:
        out.append({"role": "user", "content": results})
    return out


def to_anthropic_messages(messages: Sequence[UIMessageIn], *, partial_ids: Collection[str] = ()) -> list[dict]:
    """UIMessage[] を Anthropic の messages にする。最後は必ず新しい user の発言。

    partial_ids：DB で status=partial になっている assistant の ID。注記を足して「途中で切れた」と LLM に伝える。
    """
    if messages[-1].role != "user":
        raise InvalidMessages("最後の発言は user のテキストにしてください。")
    out: list[dict] = []
    for m in messages:
        if m.role == "system":
            raise InvalidMessages("system の発言は受け付けません。")
        if m.role == "user":
            if out and out[-1]["role"] == "user":
                out.append(note_message())  # user を連結せず、間を注記の assistant で閉じる（mid01 の決定）
            out.append({"role": "user", "content": user_blocks(m.parts)})
            continue
        converted = [msg for step in split_steps(m.parts) for msg in step_messages(step)]
        if m.id in partial_ids:
            if converted and converted[-1]["role"] == "assistant":
                converted[-1]["content"].append({"type": "text", "text": INTERRUPTED_NOTE})
            else:
                converted.append(note_message())
        out += converted
    if len(out[-1]["content"][0]["text"]) > MAX_USER_CHARS:
        raise InvalidMessages(TOO_LONG_MESSAGE)
    first = next(i for i, msg in enumerate(out) if msg["role"] == "user" and not any(
        b.get("type") == "tool_result" for b in msg["content"]))
    return out[first:]  # 画面だけの挨拶など、先頭の assistant は送らない（messages は user から始める決まり）


# ---------------------------------------------------------------- DB の発言 → UIMessage


class StoredRow(Protocol):
    id: str
    role: str
    content: list[dict]


def _output(content: object) -> object:
    if not isinstance(content, str):
        return content
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        return content


def to_ui_messages(rows: Sequence[StoredRow]) -> list[dict]:
    """保存した発言（seq 順）を UIMessage[] にする。

    1回の往復（assistant と tool_result の user の並び）を、step-start で区切った1つの assistant にまとめる。
    assistant の id は往復の最後の assistant の ID（＝その往復で start に載せた messageId）。
    """
    out: list[dict] = []
    current: dict | None = None
    pending: dict[str, dict] = {}
    for r in rows:
        results = [b for b in r.content if b.get("type") == "tool_result"]
        if r.role == "user" and not results:
            current, pending = None, {}
            text = "".join(b.get("text", "") for b in r.content if b.get("type") == "text")
            out.append({"id": r.id, "role": "user", "parts": [{"type": "text", "text": text}]})
            continue
        if r.role == "user":
            for b in results:
                part = pending.pop(b.get("tool_use_id"), None)
                if part is None:
                    continue
                if b.get("is_error"):
                    part.update(state="output-error", errorText=str(b.get("content", "")))
                else:
                    part.update(state="output-available", output=_output(b.get("content")))
            continue
        if current is None:
            current = {"id": r.id, "role": "assistant", "parts": []}
            out.append(current)
        current["id"] = r.id
        current["parts"].append({"type": "step-start"})
        for b in r.content:
            if b.get("type") == "text":
                current["parts"].append({"type": "text", "text": b["text"], "state": "done"})
            elif b.get("type") == "tool_use":
                part = {"type": f"tool-{b['name']}", "toolCallId": b["id"], "state": "input-available",
                        "input": b["input"]}
                current["parts"].append(part)
                pending[b["id"]] = part
    return out

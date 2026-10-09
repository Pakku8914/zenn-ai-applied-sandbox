"""LLM に送る messages の見積もりと切り捨て（mid01/history.py の考え方を、数え方だけ変えてコピーしたもの）。

- 注記（INTERRUPTED_NOTE）と「user を連結せず、間を注記の assistant で閉じる」は mid01 の決定のまま
- 切り捨ては Session 7 の「組」単位。ただし数えるのに count_tokens を呼ばず、mockllm と同じ近似式で見積もる
  （最終プロジェクトでは入力の見積もりを、切り捨て・クォータの予約・予算の見積もりの3か所で同じ値にしたいため）
"""

from __future__ import annotations

import json
import math
from dataclasses import replace

from .providers import ChatRequest

INTERRUPTED_NOTE = "（この応答は途中で中断されました）"


class ContextTooLong(Exception):
    """最新の組だけでも予算を超えている（これ以上は切り捨てられない）。"""


def note_message() -> dict:
    return {"role": "assistant", "content": [{"type": "text", "text": INTERRUPTED_NOTE}]}


# ---------------------------------------------------------------- 見積もり（mockllm の usage の式と同じ）


def text_tokens(text: str | None) -> int:
    return math.ceil(len(text.encode("utf-8")) / 3) if text else 0


def json_tokens(value: object) -> int:
    return text_tokens(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


def block_tokens(block: dict) -> int:
    kind = block.get("type")
    if kind == "text":
        return text_tokens(block.get("text", ""))
    if kind == "tool_use":
        return text_tokens(block.get("name", "")) + json_tokens(block.get("input", {}))
    if kind == "tool_result":
        content = block.get("content", "")
        return text_tokens(content) if isinstance(content, str) else sum(block_tokens(b) for b in content or [])
    return 0


def estimate_input_tokens(chat: ChatRequest) -> int:
    """入力トークンの見積もり＝4 ＋ ツール定義 ＋ system ＋ Σ（3 ＋ ブロック）。キャッシュは考えない。"""
    total = 4 + sum(json_tokens(t) for t in chat.tools) + text_tokens(chat.system)
    for m in chat.messages:
        content = m["content"]
        blocks = [{"type": "text", "text": content}] if isinstance(content, str) else content
        total += 3 + sum(block_tokens(b) for b in blocks)
    return total


# ---------------------------------------------------------------- 切り捨て（Session 7 の組の単位）


def is_tool_result(message: dict) -> bool:
    content = message["content"]
    return (message["role"] == "user" and isinstance(content, list)
            and any(b.get("type") == "tool_result" for b in content))


def split_groups(messages: list[dict]) -> list[list[dict]]:
    groups: list[list[dict]] = []
    for m in messages:
        if not groups or (m["role"] == "user" and not is_tool_result(m)):
            groups.append([m])
        else:
            groups[-1].append(m)
    return groups


def fit_messages(chat: ChatRequest, budget: int) -> ChatRequest:
    """見積もりが budget に収まるまで、古い組から落とす。最新の組（いま送られた発言）は必ず残す。"""
    if estimate_input_tokens(chat) <= budget:
        return chat
    groups = split_groups(chat.messages)
    for k in range(1, len(groups)):
        kept = replace(chat, messages=[m for g in groups[k:] for m in g])
        if estimate_input_tokens(kept) <= budget:
            return kept
    raise ContextTooLong()

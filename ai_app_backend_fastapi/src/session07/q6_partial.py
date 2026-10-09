"""練習問題6の解答：途中まで保存した（partial の）応答を、次の文脈にどう入れるかを選ぶ。"""

from __future__ import annotations

from typing import Literal

from .models import Message

INTERRUPTED_NOTE = "（この応答は途中で中断されました）"


def rows_of(messages: list[Message]) -> list[dict]:
    return [{"role": m.role, "content": m.content, "status": m.status} for m in messages]


def history_for_model(rows: list[dict], mode: Literal["annotate", "drop_turn"] = "annotate") -> list[dict]:
    """annotate：中断したことを書き添えて送る／drop_turn：その往復（直前の user ごと）を送らない。"""
    out: list[dict] = []
    for r in rows:
        if r["role"] == "assistant" and r["status"] == "partial":
            if mode == "drop_turn":
                if out and out[-1]["role"] == "user":
                    out.pop()
                continue
            out.append({"role": "assistant",
                        "content": [*r["content"], {"type": "text", "text": INTERRUPTED_NOTE}]})
            continue
        out.append({"role": r["role"], "content": r["content"]})
    return out

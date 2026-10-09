"""前半の練習問題3：ストリームの終わり方が API 契約③どおりかを点検する。

    docker compose exec api python -m src.session06.q7_contract
"""

from __future__ import annotations

import asyncio

from .errors import MESSAGES

TERMINAL = ("done", "error")
ERROR_KEYS = {"type", "message", "request_id"}


def contract_violations(events: list[dict], request_id: str) -> list[str]:
    """sse_events() の形のイベント列を点検し、契約から外れている点を文の列で返す（空なら契約どおり）。"""
    names = [e["event"] for e in events if e["event"] is not None]  # コメント（: ping）は数えない
    problems: list[str] = []
    if not names or names[0] != "start":
        problems.append("start で始まっていない")
    terminals = [i for i, n in enumerate(names) if n in TERMINAL]
    if len(terminals) != 1 or terminals[0] != len(names) - 1:
        problems.append("done か error のどちらか1つで終わっていない")
    errors = [e for e in events if e["event"] == "error"]
    if errors:
        data = errors[-1]["data"]
        if not isinstance(data, dict) or set(data) != ERROR_KEYS:
            problems.append("error の data のキーが type・message・request_id ではない")
        else:
            if data["message"] != MESSAGES.get(data["type"]):
                problems.append("error の message が固定文ではない")
            if data["request_id"] != request_id:
                problems.append("error の request_id が x-request-id と違う")
        if "usage" in names:
            problems.append("error で終わるのに usage を送っている")
    return problems


# 手で作った「契約から外れた」ストリーム（検査の検査に使う）
RID = "req_01K0000000000000000000000"
BAD_CASES: dict[str, list[dict]] = {
    "error のあとに done": [
        {"event": "start", "data": {"message_id": "m"}},
        {"event": "error", "data": {"type": "upstream_error", "message": MESSAGES["upstream_error"], "request_id": RID}},
        {"event": "done", "data": {"stop_reason": "end_turn"}},
    ],
    "上流の文をそのまま出した": [
        {"event": "start", "data": {"message_id": "m"}},
        {"event": "delta", "data": {"text": "鶏むね肉とキ"}},
        {"event": "error", "data": {"type": "upstream_error", "message": "Overloaded", "request_id": RID}},
    ],
    "usage のあとに error": [
        {"event": "start", "data": {"message_id": "m"}},
        {"event": "usage", "data": {"input_tokens": 34, "output_tokens": 2}},
        {"event": "error", "data": {"type": "internal_error", "message": MESSAGES["internal_error"],
                                    "request_id": "req_other"}},
    ],
}


async def main() -> None:
    for name, events in BAD_CASES.items():
        print(f"{name}: {contract_violations(events, RID)}")


if __name__ == "__main__":
    asyncio.run(main())

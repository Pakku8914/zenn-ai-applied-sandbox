"""練習問題5の解答：対になっていない tool_use / tool_result を取り除いて、送れる履歴に直す。"""

from __future__ import annotations


def _blocks(message: dict | None) -> list[dict]:
    if message is None:
        return []
    content = message["content"]
    return [{"type": "text", "text": content}] if isinstance(content, str) else list(content)


def drop_orphan_tools(messages: list[dict]) -> list[dict]:
    out: list[dict] = []
    for i, m in enumerate(messages):
        prev = messages[i - 1] if i > 0 else None
        nxt = messages[i + 1] if i + 1 < len(messages) else None
        blocks = _blocks(m)
        if m["role"] == "assistant":
            # 直後の user に結果が無い tool_use は捨てる（ストリームが途中で切れた・ツールが動く前に落ちた）
            answered = {b["tool_use_id"] for b in _blocks(nxt) if b.get("type") == "tool_result"} \
                if nxt and nxt["role"] == "user" else set()
            blocks = [b for b in blocks if b.get("type") != "tool_use" or b["id"] in answered]
        else:
            # 直前の assistant に呼び出しが無い tool_result は捨てる（呼び出し側だけ切り捨てられた）
            asked = {b["id"] for b in _blocks(prev) if b.get("type") == "tool_use"} \
                if prev and prev["role"] == "assistant" else set()
            blocks = [b for b in blocks if b.get("type") != "tool_result" or b["tool_use_id"] in asked]
        if not blocks:
            continue  # 空になった発言は消す
        if out and out[-1]["role"] == m["role"]:
            out[-1] = {**out[-1], "content": [*out[-1]["content"], *blocks]}  # 同じ role が続いたらつなぐ
        else:
            out.append({**m, "content": blocks})
    while out and out[0]["role"] != "user":
        out.pop(0)  # 先頭は user にする
    return out

"""保存した行を LLM に送る messages にする：読み替え（中断の注記）と、予算に収める切り捨て。

- split_groups・fit_history は session07/history.py から（要約の方式は使わないので写していない）
- for_model・with_new_user がこのプロジェクトで足したもの（未決事項2の決定）。
  user の発言は連結しない。user が2つ続きそうなら、間に中断の注記の assistant を挟む
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from .models import Message
from .tokens import TokenCounter

INTERRUPTED_NOTE = "（この応答は途中で中断されました）"


class ContextTooLong(Exception):
    """最新の組だけでも予算を超えている（これ以上は切り捨てられない）。"""

    def __init__(self, tokens: int, budget: int) -> None:
        super().__init__(f"{tokens} > {budget}")
        self.tokens, self.budget = tokens, budget


@dataclass(frozen=True)
class Fitted:
    messages: list[dict]  # LLM に送る messages
    dropped: list[dict] = field(default_factory=list)  # 切り捨てた古い messages
    input_tokens: int = 0  # messages を送ったときの入力トークン数
    count_calls: int = 0  # 数えるのに使った回数（count_tokens の呼び出し回数）


# ---------------------------------------------------------------- 読み替え


def note_message() -> dict:
    return {"role": "assistant", "content": [{"type": "text", "text": INTERRUPTED_NOTE}]}


def for_model(rows: Sequence[Message]) -> list[dict]:
    """保存した行を、そのまま LLM に送れる Anthropic 形式にする。status と stop_reason は送らない。"""
    out: list[dict] = []
    for r in rows:
        if r.role == "user" and out and out[-1]["role"] == "user":
            out.append(note_message())  # 旧データの保険：tool_result だけの user で終わった往復を閉じる
        content = list(r.content)
        if r.role == "assistant" and r.status == "partial":
            content.append({"type": "text", "text": INTERRUPTED_NOTE})  # 途中で切れたことを LLM に伝える
        out.append({"role": r.role, "content": content})
    return out


def with_new_user(history: list[dict], text: str) -> list[dict]:
    """新しい発言を足す。直前が user なら連結せず、注記の assistant を挟んでから足す。"""
    out = list(history)
    if out and out[-1]["role"] == "user":
        out.append(note_message())
    out.append({"role": "user", "content": [{"type": "text", "text": text}]})
    return out


# ---------------------------------------------------------------- 切り捨て（session07 から）


def is_tool_result(message: dict) -> bool:
    content = message["content"]
    return (message["role"] == "user" and isinstance(content, list)
            and any(b.get("type") == "tool_result" for b in content))


def split_groups(messages: list[dict]) -> list[list[dict]]:
    """「ふつうの user の発言」から次のそれの手前までを1組にする。tool_use と tool_result は必ず同じ組に入る。"""
    groups: list[list[dict]] = []
    for m in messages:
        if not groups or (m["role"] == "user" and not is_tool_result(m)):
            groups.append([m])
        else:
            groups[-1].append(m)
    return groups


def flatten(groups: list[list[dict]]) -> list[dict]:
    return [m for g in groups for m in g]


async def fit_history(messages: list[dict], counter: TokenCounter, *, budget: int,
                      system: str | None = None) -> Fitted:
    """予算に収まるまで古い組を落とす。落とす組の数を二分探索するので、数える回数は約 log2(組の数) 回。"""
    total = await counter.count(messages, system)
    if total <= budget:
        return Fitted(messages, [], total, 1)
    groups = split_groups(messages)
    calls, best = 1, None
    lo, hi = 1, len(groups) - 1  # 落とす組の数の候補。最後の組（いま送られた発言）は必ず残す
    while lo <= hi:
        mid = (lo + hi) // 2
        tokens = await counter.count(flatten(groups[mid:]), system)
        calls += 1
        if tokens <= budget:
            best, hi = (mid, tokens), mid - 1
        else:
            lo = mid + 1
    if best is None:
        raise ContextTooLong(total, budget)
    k, tokens = best
    return Fitted(flatten(groups[k:]), flatten(groups[:k]), tokens, calls)

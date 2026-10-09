"""練習問題7の解答：count_tokens の呼び出しを減らす（近似で当たりを付け、本物で確かめる）。"""

from __future__ import annotations

from .history import ContextTooLong, Fitted, flatten, split_groups
from .tokens import ApproxTokenCounter, TokenCounter


async def fit_history_linear(messages: list[dict], counter: TokenCounter, *, budget: int,
                             system: str | None = None) -> Fitted:
    """比較用：古い組を1つずつ落としては数え直す（数える回数は落とす組の数 + 1）。"""
    groups = split_groups(messages)
    tokens = 0
    for k in range(len(groups)):
        kept = flatten(groups[k:])
        tokens = await counter.count(kept, system)
        if tokens <= budget:
            return Fitted(kept, flatten(groups[:k]), tokens, k + 1)
    raise ContextTooLong(tokens, budget)


async def fit_history_fast(messages: list[dict], counter: TokenCounter, *, budget: int,
                           system: str | None = None, approx: TokenCounter | None = None) -> Fitted:
    approx = approx or ApproxTokenCounter()
    exact = await counter.count(messages, system)
    calls = 1
    if exact <= budget:
        return Fitted(messages, [], exact, calls)
    groups = split_groups(messages)
    ratio = exact / await approx.count(messages, system)  # この履歴での「本物 ÷ 近似」を1回だけ較正する
    k = 1
    while k < len(groups) and await approx.count(flatten(groups[k:]), system) * ratio > budget:
        k += 1  # 近似だけで当たりを付ける（ネットワークを使わない）
    while k < len(groups):
        kept = flatten(groups[k:])
        tokens = await counter.count(kept, system)  # 本物で確かめる
        calls += 1
        if tokens <= budget:
            return Fitted(kept, flatten(groups[:k]), tokens, calls)
        k += 1  # 近似が甘かったら、もう1組落とす
    raise ContextTooLong(exact, budget)

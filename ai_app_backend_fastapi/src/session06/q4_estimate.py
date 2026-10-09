"""練習問題4：system とブロックの配列も数える入力トークンの見積もり。mockllm の count_tokens と比べる。

    docker compose exec api python -m src.session06.q4_estimate
"""

from __future__ import annotations

import asyncio

import anthropic

from kondate.settings import get_settings

from .providers import ChatRequest
from .relay import estimate_tokens

PROMPT = "冷蔵庫に鶏むね肉とキャベツがある。20分で作れるものは？"
CASES = {
    "単発": ChatRequest(messages=[{"role": "user", "content": PROMPT}]),
    "system 付き": ChatRequest(messages=[{"role": "user", "content": PROMPT}],
                              system="あなたは献立の相談に乗るアシスタントです。"),
    "3件の会話": ChatRequest(messages=[
        {"role": "user", "content": PROMPT},
        {"role": "assistant", "content": "鶏むね肉とキャベツの塩炒めはいかがですか。"},
        {"role": "user", "content": [{"type": "text", "text": "副菜も教えて"}]},
    ]),
}


def estimate_input_tokens_full(chat: ChatRequest) -> int:
    """4 ＋ system ＋ Σ（メッセージごとに 3 ＋ text ブロックのトークン）。text 以外のブロックは数えない。"""
    total = 4 + (estimate_tokens(chat.system) if chat.system else 0)
    for m in chat.messages:
        content = m["content"]
        blocks = [{"type": "text", "text": content}] if isinstance(content, str) else content
        total += 3 + sum(estimate_tokens(b["text"]) for b in blocks if b.get("type") == "text")
    return total


async def count_tokens(chat: ChatRequest) -> int:
    s = get_settings()
    async with anthropic.AsyncAnthropic(base_url=s.mockllm_url, api_key="mock-key", max_retries=0) as client:
        extra = {"system": chat.system} if chat.system else {}
        result = await client.messages.count_tokens(model=s.llm_model, messages=chat.messages, **extra)
    return result.input_tokens


async def main() -> None:
    for name, chat in CASES.items():
        print(f"{name}: 見積もり {estimate_input_tokens_full(chat)} / count_tokens {await count_tokens(chat)}")


if __name__ == "__main__":
    asyncio.run(main())

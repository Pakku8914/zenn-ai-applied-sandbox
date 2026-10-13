"""問題4：前処理の有無と再試行が、usage（全試行の合計）をどう変えるかを FakeProvider で確かめる。

    docker compose exec api python -m src.review01.solutions.q4_retry_usage
"""

from __future__ import annotations

import asyncio
import json
import logging
import math

from kondate.llm import ChatResult, FakeProvider, Usage
from src.review01 import samples
from src.review01.kit import FRIDGE_PROMPT, InvalidOutput, estimate_image_tokens, prepare_image, scan_fridge

logging.getLogger("src.review01").setLevel(logging.ERROR)  # 失敗をわざと作るので、警告ログは表示しない

NAMES = ["キャベツ", "鶏むね肉", "卵", "にんじん", "牛乳"]
OUTPUT_TOKENS = 194  # fridge.jpg を mockllm に送ったときと同じ値にそろえる
PROMPT_TOKENS = math.ceil(len(FRIDGE_PROMPT.encode("utf-8")) / 3)


def input_tokens(size: tuple[int, int]) -> int:
    """問題3と同じ内訳：枠 7 ＋ 画像 ＋ 指示文。"""
    return 7 + estimate_image_tokens(*size) + PROMPT_TOKENS


def answer(inp: int, first_confidence: float = 0.9) -> ChatResult:
    items = [{"name": n, "quantity": "1個", "amount": 1, "unit": "個", "confidence": 0.9, "category": "野菜"} for n in NAMES]
    items[0]["confidence"] = first_confidence
    return ChatResult(json.dumps({"ingredients": items}, ensure_ascii=False), [], "end_turn", Usage(inp, OUTPUT_TOKENS))


def cut(inp: int) -> ChatResult:
    return ChatResult('{"ingredients": [{"name": "キャ', [], "max_tokens", Usage(inp, 100))


async def outcome(jpeg: bytes, results: list[ChatResult]) -> str:
    fake = FakeProvider(results)
    try:
        r = await scan_fridge(fake, jpeg)
        status, attempts, usage = "200", r.attempts, r.usage
    except InvalidOutput as e:
        status, attempts, usage = "502 invalid_output", e.attempts, e.usage  # 失敗しても usage は残っている
    assert attempts == len(fake.requests), (attempts, len(fake.requests))
    return f"{status}・試行 {attempts} 回・usage {usage.input_tokens}/{usage.output_tokens}"


async def run() -> None:
    fridge = prepare_image(samples.fridge())
    large_raw = samples.large()
    large = prepare_image(large_raw)
    f = input_tokens(fridge.sent_size)
    lp = input_tokens(large.sent_size)
    lr = input_tokens(large.stored_size)
    rows = [
        ("fridge.jpg（前処理あり）・正常", fridge.data, [answer(f)]),
        ("fridge.jpg（前処理あり）・範囲外→正常", fridge.data, [answer(f, 1.5), answer(f)]),
        ("fridge.jpg（前処理あり）・範囲外が2回", fridge.data, [answer(f, 1.5), answer(f, 1.5)]),
        ("fridge.jpg（前処理あり）・max_tokens で切れた", fridge.data, [cut(f), answer(f)]),  # 2つ目は使われない
        ("4000×3000（前処理あり）・範囲外→正常", large.data, [answer(lp, 1.5), answer(lp)]),
        ("4000×3000（前処理なし）・範囲外→正常", large_raw, [answer(lr, 1.5), answer(lr)]),
    ]
    for label, jpeg, results in rows:
        print(f"{label}: {await outcome(jpeg, results)}")


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()

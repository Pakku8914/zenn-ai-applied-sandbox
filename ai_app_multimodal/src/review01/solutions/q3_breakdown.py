"""問題3：入力トークンの内訳を式で組み立て、count_tokens の値と照合する。

    docker compose exec api python -m src.review01.solutions.q3_breakdown
"""

from __future__ import annotations

import math

from anthropic import Anthropic

from kondate.settings import get_settings
from src.review01 import samples
from src.review01.kit import FRIDGE_PROMPT, base64_block, estimate_image_tokens, prepare_image

FRAME_TOKENS = 4 + 3  # リクエスト1件の枠（4）＋メッセージ1件の枠（3）


def text_tokens(text: str) -> int:
    """mockllm の近似式：UTF-8 のバイト数を 3 で割って切り上げる。"""
    return math.ceil(len(text.encode("utf-8")) / 3)


def breakdown(width: int, height: int) -> tuple[int, int, int, int]:
    image = estimate_image_tokens(width, height)
    prompt = text_tokens(FRIDGE_PROMPT)
    return FRAME_TOKENS, image, prompt, FRAME_TOKENS + image + prompt


def counted(client: Anthropic, jpeg: bytes) -> int:
    content = [base64_block(jpeg), {"type": "text", "text": FRIDGE_PROMPT}]
    res = client.messages.count_tokens(model=get_settings().llm_model, messages=[{"role": "user", "content": content}])
    return res.input_tokens


def cases() -> list[tuple[str, bytes, tuple[int, int]]]:
    fridge = prepare_image(samples.fridge())
    large = prepare_image(samples.large())
    return [
        ("fridge.jpg（前処理あり）", fridge.data, fridge.sent_size),
        ("4000×3000（前処理あり）", large.data, large.sent_size),
        ("4000×3000（前処理なし）", samples.large(), large.stored_size),
    ]


def main() -> None:
    client = Anthropic()
    try:
        for label, jpeg, (w, h) in cases():
            frame, image, prompt, total = breakdown(w, h)
            got = counted(client, jpeg)
            print(f"{label}: 枠 {frame} + 画像 {image} + 指示文 {prompt} = {total} ／ "
                  f"count_tokens {got} ／ {'一致' if got == total else '不一致'}")
    finally:
        client.close()


if __name__ == "__main__":
    main()

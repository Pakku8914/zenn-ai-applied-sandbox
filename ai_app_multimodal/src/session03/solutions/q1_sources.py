"""問題1：source の種類から image ブロックを組み立て、count_tokens で数え方の違いを確かめる。

    docker compose exec api python -m src.session03.solutions.q1_sources
"""

from __future__ import annotations

import base64

from anthropic import Anthropic

from kondate.media import media_path
from kondate.settings import get_settings

IMAGE_MEDIA_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}


def make_image_block(source_type: str, value: bytes | str, media_type: str | None = None) -> dict:
    if source_type == "base64":
        if not isinstance(value, bytes):
            raise TypeError("base64 には画像のバイト列を渡してください")
        if media_type not in IMAGE_MEDIA_TYPES:
            raise ValueError(f"media_type は {sorted(IMAGE_MEDIA_TYPES)} のいずれかです")
        source = {"type": "base64", "media_type": media_type, "data": base64.standard_b64encode(value).decode("ascii")}
    elif source_type == "url":
        if not isinstance(value, str) or not value.startswith("https://"):
            raise ValueError("url は https:// で始まる文字列にしてください")
        source = {"type": "url", "url": value}
    elif source_type == "file":
        if not isinstance(value, str) or not value.startswith("file_"):
            raise ValueError("file_id は file_ で始まる文字列にしてください")
        source = {"type": "file", "file_id": value}
    else:
        raise ValueError(f"source_type は base64・url・file のいずれかです（{source_type!r}）")
    return {"type": "image", "source": source}


def count(client: Anthropic, block: dict) -> int:
    res = client.messages.count_tokens(model=get_settings().llm_model, messages=[{"role": "user", "content": [block]}])
    return res.input_tokens


def main() -> None:
    blocks = {
        "base64": make_image_block("base64", media_path("fridge.jpg").read_bytes(), "image/jpeg"),
        "url": make_image_block("url", "https://example.com/fridge.jpg"),
        "file": make_image_block("file", "file_demo_fridge_0001"),
    }
    client = Anthropic()
    try:
        for name, block in blocks.items():
            print(f"{name:<6} input_tokens={count(client, block)}")
    finally:
        client.close()


if __name__ == "__main__":
    main()

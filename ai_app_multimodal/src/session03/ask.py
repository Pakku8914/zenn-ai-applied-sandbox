"""同じ質問を、file_id で参照した画像と base64 で同封した画像の2通りで送る。

    docker compose exec api python -m src.session03.ask
"""

from __future__ import annotations

from anthropic import Anthropic

from kondate.media import media_path
from kondate.settings import get_settings
from src.session03.images import base64_block, file_block, prepare_image

QUESTION = "この写真に写っている食材は何ですか？"
DUMMY_FILE_ID = "file_demo_fridge_0001"  # mockllm は中身を取りに行かないので任意の文字列でよい


def main() -> None:
    s = get_settings()
    p = prepare_image(media_path("fridge.jpg").read_bytes())
    client = Anthropic()
    try:
        for name, block in (("file", file_block(DUMMY_FILE_ID)), ("base64", base64_block(p.data, p.media_type))):
            msg = client.messages.create(
                model=s.llm_model, max_tokens=s.llm_max_tokens,
                messages=[{"role": "user", "content": [block, {"type": "text", "text": QUESTION}]}],
            )
            first_line = msg.content[0].text.splitlines()[0]
            print(f"{name:<6} input_tokens={msg.usage.input_tokens} 「{first_line}」")
    finally:
        client.close()


if __name__ == "__main__":
    main()

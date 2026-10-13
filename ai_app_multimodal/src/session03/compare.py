"""前処理の前後で、送る寸法と画像トークン（mockllm の count_tokens）を比べる。

    docker compose exec api python -m src.session03.compare
"""

from __future__ import annotations

from anthropic import Anthropic

from kondate.media import media_path
from src.session03.count import FRAME_TOKENS, count_input_tokens
from src.session03.images import base64_block, prepare_image
from src.session03.make_variants import make_all


def main() -> None:
    paths = make_all()
    targets = {"fridge.jpg": media_path("fridge.jpg"), **{p.name: p for p in paths.values()}}
    client = Anthropic()  # 接続先は環境変数 ANTHROPIC_BASE_URL（既定は mockllm）
    try:
        for name, path in targets.items():
            raw = path.read_bytes()
            p = prepare_image(raw)
            before = count_input_tokens(client, [base64_block(raw)]) - FRAME_TOKENS
            after = count_input_tokens(client, [base64_block(p.data, p.media_type)]) - FRAME_TOKENS
            sw, sh = p.stored_size
            tw, th = p.sent_size
            removed = "はい" if p.exif_removed else "いいえ"
            print(f"{name:<20} 保存 {sw}×{sh} → 送信 {tw}×{th} ／ 画像トークン {before} → {after} ／ EXIF を除去: {removed}")
    finally:
        client.close()


if __name__ == "__main__":
    main()

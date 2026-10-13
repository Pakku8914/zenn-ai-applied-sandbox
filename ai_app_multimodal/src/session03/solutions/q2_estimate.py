"""問題2：寸法から画像トークンを見積もり、count_tokens と照合する。

    docker compose exec api python -m src.session03.solutions.q2_estimate
"""

from __future__ import annotations

import base64
import io
import math

from anthropic import Anthropic
from PIL import Image

from kondate.settings import get_settings

MAX_LONG_EDGE = 2576
MAX_TOKENS = 4784
PATCH = 28
FRAME_TOKENS = 7
SIZES = [(100, 100), (600, 900), (1280, 960), (960, 1280), (1568, 1176), (2000, 1500), (4000, 3000), (5152, 300)]


def estimate(width: int, height: int) -> int:
    scale = min(1.0, MAX_LONG_EDGE / max(width, height))
    w, h = max(1, round(width * scale)), max(1, round(height * scale))
    return min(MAX_TOKENS, math.ceil(w / PATCH) * math.ceil(h / PATCH))


def counted(client: Anthropic, width: int, height: int) -> int:
    buf = io.BytesIO()
    Image.new("RGB", (width, height), (255, 255, 255)).save(buf, "PNG")  # 寸法だけが要るので白紙でよい
    data = base64.standard_b64encode(buf.getvalue()).decode("ascii")
    block = {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": data}}
    res = client.messages.count_tokens(model=get_settings().llm_model, messages=[{"role": "user", "content": [block]}])
    return res.input_tokens - FRAME_TOKENS


def main() -> None:
    client = Anthropic()
    try:
        for w, h in SIZES:
            est, got = estimate(w, h), counted(client, w, h)
            print(f"{w}×{h}: 見積もり {est} ／ count_tokens−7 {got} ／ {'一致' if est == got else '不一致'}")
    finally:
        client.close()


if __name__ == "__main__":
    main()

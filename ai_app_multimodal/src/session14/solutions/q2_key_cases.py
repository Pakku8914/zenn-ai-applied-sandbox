"""問題2：キャッシュキーの材料を見極める（どの再送が命中し、どれが外れるか）。

    docker compose exec api python -m src.session14.solutions.q2_key_cases
"""

from __future__ import annotations

import io

from PIL import Image, ImageOps

from kondate.media import media_path
from kondate.settings import get_settings
from src.session14.app import FRIDGE_PROMPT, JPEG_QUALITY, PREPROCESS
from src.session14.cache import cache_key, sha256_hex
from src.session14.intake import accept_image
from src.session14.models import FRIDGE_SCHEMA

S = get_settings()
FRIDGE = media_path("fridge.jpg").read_bytes()


def to_png(raw: bytes) -> bytes:
    """同じ写真（向きを直した同じ画素）を PNG にしたもの。"""
    with Image.open(io.BytesIO(raw)) as img:
        out = io.BytesIO()
        ImageOps.exif_transpose(img).convert("RGB").save(out, "PNG")
    return out.getvalue()


def key_for(raw: bytes, *, user_id: str = "u001", filename: str = "fridge.jpg",
            max_long_edge: int = PREPROCESS["max_long_edge"], prompt: str = FRIDGE_PROMPT,
            model: str | None = None, schema: dict = FRIDGE_SCHEMA) -> str:
    # filename（と Content-Type）はキーに入れない。形式は中身で決めるので、名前が違っても同じ写真は同じ結果になる
    return cache_key(scope=user_id, kind="fridge_scan", content_sha256=sha256_hex(raw),
                     preprocess={"max_long_edge": max_long_edge, "jpeg_quality": JPEG_QUALITY},
                     prompt=prompt, system=None, model=model or S.llm_model, schema=schema)


def key_after_preprocess(raw: bytes, user_id: str = "u001") -> str:
    """別解：前処理した後の JPEG のバイト列でキーを作る（前処理の分の CPU は毎回かかる）。"""
    jpeg = accept_image(raw, PREPROCESS["max_long_edge"], JPEG_QUALITY).data
    return cache_key(scope=user_id, kind="fridge_scan", content_sha256=sha256_hex(jpeg), preprocess=PREPROCESS,
                     prompt=FRIDGE_PROMPT, system=None, model=S.llm_model, schema=FRIDGE_SCHEMA)


def cases() -> list[tuple[str, str]]:
    png = to_png(FRIDGE)
    return [
        ("同じ写真をもう一度送った", key_for(FRIDGE)),
        ("ファイル名だけ fridge_copy.jpg に変えた", key_for(FRIDGE, filename="fridge_copy.jpg")),
        ("u002 が同じ写真を送った", key_for(FRIDGE, user_id="u002")),
        ("同じ写真を PNG に変換して送った", key_for(png)),
        ("縮小の上限を 1024 に変えた", key_for(FRIDGE, max_long_edge=1024)),
        ("プロンプトに「調味料は除いてください。」を足した", key_for(FRIDGE, prompt=FRIDGE_PROMPT + "調味料は除いてください。")),
        ("モデルを LLM_MODEL_LIGHT に変えた", key_for(FRIDGE, model=S.llm_model_light)),
        ("スキーマに説明文を足した", key_for(FRIDGE, schema={**FRIDGE_SCHEMA, "description": "冷蔵庫の食材"})),
    ]


def run() -> list[str]:
    base = key_for(FRIDGE)
    lines = [f"{i}. {label}：{'命中' if key == base else '外れ'}" for i, (label, key) in enumerate(cases(), 1)]
    same = key_after_preprocess(to_png(FRIDGE)) == key_after_preprocess(FRIDGE)
    lines.append(f"別解（前処理した後の JPEG でキーを作る）では 4 が{'命中' if same else '外れ'}になる")
    return lines


def main() -> None:
    print("\n".join(run()))


if __name__ == "__main__":
    main()

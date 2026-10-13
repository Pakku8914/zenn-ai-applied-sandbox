"""問題1：同じファイルを、アップロードの窓口（セッション2）と音声認識の窓口（セッション8）に送り、
通ったら次の処理に渡す量（画像・文書のトークン、16kHz のサンプル数）を出す。

    docker compose exec api python -m src.review03.solutions.q1_two_windows
"""

from __future__ import annotations

import io

from PIL import Image
from pypdf import PdfReader

from kondate.settings import get_settings
from src.review03 import samples
from src.review03.kit import (
    MSG_TOO_LARGE, PDF_TOKENS_PER_PAGE, TARGET_RATE, UPLOAD_MAX_BYTES, AudioRejected, Rejected, decode_wav,
    estimate_image_tokens, inspect_upload, tone_wav,
)

LONG_EDGE = get_settings().image_max_long_edge   # 1568（セッション3の前処理）


def prepared_size(width: int, height: int, limit: int = LONG_EDGE) -> tuple[int, int]:
    """前処理（長辺を limit まで縮める。拡大はしない）のあとの寸法。"""
    scale = min(1.0, limit / max(width, height))
    return max(1, round(width * scale)), max(1, round(height * scale))


def next_tokens(raw: bytes, kind: str) -> str:
    """LLM に送るとしたら何トークンか（画像はセッション3の式、PDF はページ数×1600）。"""
    if kind == "image":
        with Image.open(io.BytesIO(raw)) as img:
            return f"画像 {estimate_image_tokens(*prepared_size(*img.size))} トークン"
    return f"文書 {len(PdfReader(io.BytesIO(raw)).pages) * PDF_TOKENS_PER_PAGE} トークン"


def via_uploads(raw: bytes, messages: set) -> str:
    if len(raw) > UPLOAD_MAX_BYTES:                      # 中身を見る前に、大きさで断る
        messages.add((413, MSG_TOO_LARGE))
        return "413 too_large"
    try:
        kind, _ = inspect_upload(raw)
    except Rejected as e:
        messages.add((e.status, e.message))
        return f"{e.status} {e.type}"
    return f"201 {kind}・{next_tokens(raw, kind)}"


def via_transcribe(raw: bytes, messages: set) -> str:
    if len(raw) > UPLOAD_MAX_BYTES:
        messages.add((413, MSG_TOO_LARGE))
        return "413 too_large"
    try:
        audio = decode_wav(raw)                          # RIFF/WAVE の目印 → 16bit → 秒数 → 16kHz モノラル
    except AudioRejected as e:
        messages.add((e.status, e.message))
        return f"{e.status} {e.type}"
    return f"OK・16kHz {len(audio)} サンプル（{len(audio) / TARGET_RATE:.2f} 秒）"


def inputs() -> list[tuple[str, bytes]]:
    return [
        ("receipt.png", samples.receipt_png()),
        ("fridge.jpg", samples.fridge_jpg()),
        ("無地の JPEG（4000×3000）", samples.plain_jpeg(4000, 3000)),
        ("receipt.pdf", samples.receipt_pdf()),
        ("WAV 24kHz・1秒", tone_wav(24000, 1.0)),
        ("WAV 16kHz・60秒", tone_wav(16000, 60.0)),
        ("WAV 16kHz・61秒", tone_wav(16000, 61.0)),
        ("WAV 48kHz・ステレオ・54秒", tone_wav(48000, 54.0, channels=2)),
        ("WAV 48kHz・ステレオ・55秒", tone_wav(48000, 55.0, channels=2)),
        ("WAV 16kHz・0.05秒", tone_wav(16000, 0.05)),
        ("WAV 8bit・1秒", tone_wav(16000, 1.0, sampwidth=1)),
    ]


def fixed_texts(messages: set) -> str:
    return "・".join(f"{status}「{message}」" for status, message in sorted(messages))


def main() -> None:
    upload_msgs: set = set()
    voice_msgs: set = set()
    for label, raw in inputs():
        print(f"{label} → uploads {via_uploads(raw, upload_msgs)} ／ transcribe {via_transcribe(raw, voice_msgs)}")
    print(f"uploads の固定文: {fixed_texts(upload_msgs)}")
    print(f"transcribe の固定文: {fixed_texts(voice_msgs)}")


if __name__ == "__main__":
    main()
